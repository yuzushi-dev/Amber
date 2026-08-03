"""
Query API Routes
================

Endpoints for querying the knowledge base.
Phase 2: Baseline RAG implementation with vector retrieval and LLM generation.
"""

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from inspect import isawaitable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.generation.domain.memory_models import ConversationSummary

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import (
    RequestRlsContext,
    get_db_session,
    get_request_rls_context,
    request_rls_session,
)
from src.api.schemas.query import (
    QueryRequest,
    QueryResponse,
    StructuredQueryResponse,
    TimingInfo,
)
from src.shared.refusal import text_looks_like_refusal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/query", tags=["query"])

# =============================================================================
# Service Dependencies
# =============================================================================


def _get_tenant_id(request: Request) -> str:
    """Extract tenant ID from request context. Raises 401 if not authenticated."""
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: tenant context missing.",
        )
    return str(tenant_id)


def _get_user_id(request: Request) -> str:
    """Resolve user identity from X-User-ID header or authenticated API key name.

    Server-to-server callers may pass X-User-ID explicitly.
    Browser/frontend callers without the header fall back to the API key name
    so every authenticated caller gets a stable, non-shared identity.
    """
    user_id = (request.headers.get("X-User-ID") or "").strip()
    if not user_id:
        user_id = getattr(request.state, "api_key_name", "") or ""
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not resolve user identity: provide X-User-ID or authenticate with a named API key.",
        )
    return user_id


def _get_api_key_id(request: Request) -> str | None:
    """Authenticated API-key identity: immutable, unspoofable, set by the auth
    middleware for every valid key (`request.state.api_key_id`).

    Unlike `_get_user_id()` above, this is never taken from a request header.
    It is the correct ownership key for security-relevant decisions —
    deciding whose conversation history gets re-injected into a retrieval
    context, or which group an admin metrics row belongs to — because
    `_get_user_id()`'s value (X-User-ID, or the API key *name* as fallback)
    is exactly what a caller controls and can set to match another user's
    stored identity. `None` here means no authenticated key could be
    resolved; callers must treat that as "deny", not "no filter".
    """
    return getattr(request.state, "api_key_id", None)


# =============================================================================
# Query Endpoint
# =============================================================================


@router.post(
    "",
    status_code=status.HTTP_200_OK,
    summary="Query the Knowledge Base",
    description="""
    Submit a natural language query to retrieve relevant information
    from the knowledge base.

    **Phase 2 Implementation**: Vector retrieval with LLM answer generation.
    - Embeds query and searches Milvus for relevant chunks
    - Reranks results using FlashRank
    - Generates answer with citations using LLM

    **Structured Queries**: List/count queries are executed directly via Cypher
    for instant responses without LLM generation.
    """,
    responses={
        200: {
            "description": "Query response (can be QueryResponse or StructuredQueryResponse)",
            "content": {
                "application/json": {
                    "examples": {
                        "rag_response": {
                            "summary": "RAG Response",
                            "value": {"answer": "...", "sources": [], "timing": {}},
                        },
                        "structured_response": {
                            "summary": "Structured Query Response",
                            "value": {"query_type": "list_documents", "data": [], "count": 0},
                        },
                    }
                }
            },
        }
    },
)
async def query(
    request: QueryRequest, http_request: Request, session: AsyncSession = Depends(get_db_session)
) -> QueryResponse | StructuredQueryResponse:
    """
    Query the knowledge base.

    Executes the full RAG pipeline:
    1. Embed query (with caching)
    2. Vector search in Milvus
    3. Rerank results
    4. Generate answer with LLM
    5. Return answer with citations and timing

    Args:
        request: Query request with question and options
        http_request: FastAPI request for context

    Returns:
        QueryResponse: Answer with sources and timing
    """
    from src.amber_platform.composition_root import (
        build_generation_service,
        build_metrics_collector,
        build_retrieval_service,
    )
    from src.core.retrieval.application.use_cases_query import QueryUseCase

    tenant_id = _get_tenant_id(http_request)

    # Instantiate Use Case using Composition Root factories
    try:
        use_case = QueryUseCase(
            retrieval_service=build_retrieval_service(session),
            generation_service=build_generation_service(session),
            metrics_collector=build_metrics_collector(),
        )

        # Determine User ID (extract logic from previous implementation)
        user_id = _get_user_id(http_request)
        api_key_id = _get_api_key_id(http_request)
        conversation_history: list[dict] | None = None
        from src.api.config import settings as history_settings

        if history_settings.enable_multiturn_history_reinjection:
            conversation_history = await _load_conversation_history(
                session, request.conversation_id, tenant_id, api_key_id
            )

        response = await use_case.execute(
            request=request,
            tenant_id=tenant_id,
            http_request_state=http_request.state,
            user_id=user_id,
            conversation_history=conversation_history,
        )

        # Persist conversation summary in Postgres (mirrors streaming path).
        # getattr, not attribute access: this route also returns
        # StructuredQueryResponse (list/count/aggregate queries), which has no
        # conversation_id. A plain `response.conversation_id` raises there, and the
        # broad `except Exception` below turns that into the generic "unable to
        # process your query" fallback - i.e. every structured query on this
        # endpoint fails, with the real reason only visible in the logs.
        if user_id and getattr(response, "conversation_id", None):
            try:
                from sqlalchemy.orm.attributes import flag_modified

                from src.core.generation.domain.memory_models import ConversationSummary

                # Serialize sources to plain dicts (matching stream path's collected_sources shape)
                response_sources = [
                    s.model_dump() if hasattr(s, "model_dump") else dict(s)
                    for s in (response.sources or [])
                ]
                title_text = (
                    request.query[:50] + "..." if len(request.query) > 50 else request.query
                )
                # Refusals aren't persisted as reusable summary text: fed back as
                # PAST CONVERSATIONS memory context, they bias the retrieval-time
                # query rewriter into repeating/worsening the same miss.
                summary_text = (
                    ""
                    if _looks_like_refusal(response.answer, response.sources)
                    else (
                        response.answer[:200] + "..."
                        if len(response.answer) > 200
                        else response.answer
                    )
                ) if response.answer else ""

                async with request_rls_session(get_request_rls_context(http_request)) as mem_session:
                    existing_summary = await mem_session.get(
                        ConversationSummary, response.conversation_id
                    )

                    existing_summary = _resolve_owned_summary(existing_summary, tenant_id, api_key_id)
                    if existing_summary:
                        # UPDATE: append current turn to history[], refresh top-level fields
                        history = existing_summary.metadata_.get("history", [])
                        history.append(
                            {
                                "query": request.query,
                                "answer": response.answer,
                                "sources": response_sources,
                                "routing_info": {"categories": ["Imported Docs"], "confidence": 1.0},
                                "timestamp": _utc_now_iso(),
                            }
                        )
                        existing_summary.metadata_["history"] = history
                        existing_summary.metadata_["query"] = request.query
                        existing_summary.metadata_["answer"] = response.answer
                        existing_summary.metadata_["timestamp"] = _utc_now_iso()
                        flag_modified(existing_summary, "metadata_")
                        mem_session.add(existing_summary)
                        logger.info(
                            f"Updated non-stream RAG conversation history: {existing_summary.id}"
                        )
                    else:
                        # INSERT: new conversation with first-turn history entry
                        new_summary = ConversationSummary(
                            id=response.conversation_id,
                            tenant_id=tenant_id,
                            user_id=user_id,
                            api_key_id=api_key_id,
                            title=title_text,
                            summary=summary_text,
                            metadata_={
                                "query": request.query,
                                "answer": response.answer,
                                "sources": response_sources,
                                "model": "rag-default",
                                "mode": "rag",
                                "history": [
                                    {
                                        "query": request.query,
                                        "answer": response.answer,
                                        "sources": response_sources,
                                        "routing_info": {
                                            "categories": ["Imported Docs"],
                                            "confidence": 1.0,
                                        },
                                        "timestamp": _utc_now_iso(),
                                    }
                                ],
                            },
                        )
                        mem_session.add(new_summary)
                        logger.info(
                            f"Saved non-stream RAG conversation history: {new_summary.id}"
                        )
            except Exception as mem_e:
                logger.warning(f"Conversation history save skipped: {mem_e}")

        return response

    except Exception as e:
        start_time = time.perf_counter()  # Fallback Start Time
        logger.error(f"Query execution failed: {e}")
        return _fallback_response(request, start_time, str(e))


def _fallback_response(
    request: QueryRequest,
    start_time: float,
    error: str,
) -> QueryResponse:
    """Generate a fallback response when services fail."""
    elapsed = (time.perf_counter() - start_time) * 1000

    return QueryResponse(
        answer=(
            f"I'm unable to process your query at the moment. "
            f"Error: {error}\n\n"
            f'Your query: "{request.query[:100]}{"..." if len(request.query) > 100 else ""}"'
        ),
        sources=[],
        trace=None,
        timing=TimingInfo(
            total_ms=round(elapsed, 2),
            retrieval_ms=None,
            generation_ms=None,
        ),
        conversation_id=request.conversation_id,
        follow_up_questions=[
            "Please check that the system is properly configured",
            "Ensure API keys are set in the environment",
        ],
    )


def _score_from_chunk(chunk: Any) -> float:
    if isinstance(chunk, dict):
        return float(chunk.get("score", 0))
    return float(getattr(chunk, "score", 0))


def _build_quality_data(chunks: list[Any]) -> dict[str, float]:
    scores = [_score_from_chunk(chunk) for chunk in chunks]
    max_score = max(scores) if scores else 0
    quality = round(max_score * 100, 1)
    return {
        "total": quality,
        "retrieval": quality,
        "generation": 0,
    }


def _build_graph_sources(collected_sources: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not collected_sources:
        return []

    return [
        {
            "chunk_id": source.get("chunk_id"),
            "document_id": source.get("document_id"),
            "score": source.get("score"),
        }
        for source in collected_sources
    ]


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _looks_like_refusal(answer: str, sources: list[Any] | None = None) -> bool:
    """Detect a "no information found" answer so it isn't persisted as reusable
    memory context — a refusal fed back as PAST CONVERSATIONS biases the
    retrieval-time query rewriter into repeating/worsening the same miss.

    Refusals now carry sources (the dignified-refusal "Closest documented
    topics" section), so a no-sources check alone is insufficient; delegate the
    text test to the shared detector, which is adverb-tolerant and matches the
    refusal section marker."""
    if not sources:
        return True
    return text_looks_like_refusal(answer)


# =============================================================================
# Multi-turn conversation history
# =============================================================================

# Deterministic length guards applied before conversation history is handed to
# the retrieval query-rewriter / generator. Observed prod answers reach up to
# 3687 chars (p95 2622) — unbounded, that blows out the rewrite prompt with
# content that's mostly a restatement of already-cited sources.
MAX_HISTORY_ANSWER_CHARS = 2000  # per-answer cap (p95 observed 2622, max 3687)
# Separate, smaller cap for the *query* half of a turn — user queries are
# short in practice, and giving them the same 2000-char budget as answers
# would let two capped answers alone (2 * (2000 + 1 ellipsis char) = 4002)
# eat almost the entire total budget below, leaving ~198 chars for both
# queries *combined*. At p95 (answer 2622 chars, over MAX_HISTORY_ANSWER_CHARS,
# so both answers land on the cap-plus-ellipsis case) any pair of queries
# over ~99 chars would then push the older turn out — collapsing the
# "2 turns" window to 1 in the typical case, not just a pathological one.
MAX_HISTORY_QUERY_CHARS = 300
# Cap on the combined injected turns (up to 2 turns of user query + assistant
# answer each). Sized so two turns at the p95 answer size (capped to
# MAX_HISTORY_ANSWER_CHARS each) plus two realistic-length queries
# (~150 chars each, well under MAX_HISTORY_QUERY_CHARS) both survive:
# 2 * 2000 + 2 * 150 = 4300, comfortably under this cap. This is what ends
# up in the rewriter prompt alongside the live query.
MAX_HISTORY_TOTAL_CHARS = 4600


def _cap_text(text: str, limit: int) -> str:
    """Deterministically truncate `text` to at most `limit` characters."""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _history_turns_to_messages(turns: list[dict], max_turns: int = 2) -> list[dict]:
    """Map persisted history turns ({query, answer, ...}) to the {role, content}
    message format the query rewriter and LLM providers expect. Keeps only the
    last ``max_turns`` turns (each turn → a user + an assistant message), each
    answer capped at MAX_HISTORY_ANSWER_CHARS and each query capped at the
    separate, smaller MAX_HISTORY_QUERY_CHARS.

    Each turn is an atomic unit: it is included whole (both its messages,
    after per-message capping) or not at all — never split across the user/
    assistant boundary. Turns are walked newest-first so that when the
    combined MAX_HISTORY_TOTAL_CHARS budget runs out, it's the *oldest*
    turns that get dropped and the most recent (most relevant to a
    follow-up) that survive; the result is then restored to chronological
    (user-first) order.

    A malformed turn — not a dict, or an `answer` present but not a string
    (corrupted/legacy data) — is skipped entirely rather than raising: one
    bad turn must not cost the caller every other, well-formed turn in the
    conversation (see _load_conversation_history's try/except, which used to
    be the only backstop and discarded the *whole* history on any error).
    A turn with no `answer` at all (not yet answered) is not malformed: its
    user message is still kept.

    Default 2 turns (= 4 messages): QueryRewriter.rewrite() truncates to the last
    5 *messages*, so a wider window would be sliced mid-turn and could start on an
    assistant message. 2 whole turns survive that slice intact, user-first.
    A deeper window would require the rewriter to truncate by turns (follow-up).

    max_turns <= 0 returns [] rather than slicing with ``[-0:]``, which is
    ``[0:]`` — i.e. *every* turn, the opposite of "keep none"."""
    if max_turns <= 0:
        return []
    candidate_turns = (turns or [])[-max_turns:]

    kept_groups: list[list[dict]] = []
    total_chars = 0
    for turn in reversed(candidate_turns):
        if not isinstance(turn, dict):
            continue
        q = turn.get("query")
        a = turn.get("answer")
        if a is not None and not isinstance(a, str):
            # Malformed turn (e.g. answer of the wrong type): drop this turn
            # only, don't let it poison the turns around it.
            continue

        group: list[dict] = []
        group_chars = 0
        if q:
            q_capped = _cap_text(str(q), MAX_HISTORY_QUERY_CHARS)
            group.append({"role": "user", "content": q_capped})
            group_chars += len(q_capped)
        # Drop refusal answers ("no documentation found …"): re-feeding them as
        # assistant context re-poisons the rewriter/generator — the same reason
        # _looks_like_refusal blanks the stored summary. Keep the user turn.
        #
        # Text-only check (not _looks_like_refusal): orchestrator.py hardcodes
        # sources=[] for agent-mode turns, so _looks_like_refusal's
        # `if not sources: return True` would discard 100% of agent-mode
        # assistant turns here. text_looks_like_refusal looks only at the
        # answer text, which is what this history re-injection cares about.
        if a and not text_looks_like_refusal(a):
            a_capped = _cap_text(a, MAX_HISTORY_ANSWER_CHARS)
            group.append({"role": "assistant", "content": a_capped})
            group_chars += len(a_capped)

        if not group:
            continue
        if total_chars + group_chars > MAX_HISTORY_TOTAL_CHARS:
            # Stop rather than skip ahead: we want a *contiguous* window of
            # the most recent turns, not an optimal bin-packing of the
            # budget. An older turn can be small enough to fit in whatever
            # budget remains, but it's still dropped here, because a more
            # recent turn already didn't fit — skipping past that gap would
            # inject a non-contiguous set of turns (e.g. turn N and turn
            # N-2 but not N-1), which is a worse trade-off for a follow-up
            # question than a shorter but unbroken recent window.
            break
        kept_groups.append(group)
        total_chars += group_chars

    messages: list[dict] = []
    for group in reversed(kept_groups):
        messages.extend(group)
    return messages


async def _load_conversation_history(
    session: AsyncSession,
    conversation_id: str | None,
    tenant_id: str,
    api_key_id: str | None,
    max_turns: int = 2,
) -> list[dict]:
    """Load prior turns of a conversation as {role, content} messages so the
    retrieval query-rewriter (and generation) can resolve follow-up questions
    against earlier context. Returns [] for a new/unknown conversation or on any
    error (fail open — retrieval simply falls back to treating the query as
    standalone, i.e. today's behaviour).

    Ownership is gated on the authenticated `api_key_id`
    (`request.state.api_key_id`), not on `user_id`/X-User-ID: the latter is a
    caller-controlled header, and gating a cross-request content injection on
    it let one authenticated caller read another user's conversation history
    by guessing `conversation_id` and sending an `X-User-ID` equal to the
    victim's resolved identity (issue #72). A row written before this
    ownership model existed carries `api_key_id=None` and never matches —
    fail closed, no backfill; the row is still readable once a later
    authenticated write adopts it (see the persistence functions below).

    Runs inside the stream's short pre-provider RLS phase, so the summary is
    read under all request GUCs and is detached before provider streaming
    begins."""
    if not conversation_id or not api_key_id:
        return []
    try:
        from src.core.generation.domain.memory_models import ConversationSummary

        summary = await session.get(ConversationSummary, conversation_id)
        if (
            not summary
            or summary.tenant_id != tenant_id
            or not summary.api_key_id
            or summary.api_key_id != api_key_id
        ):
            return []
        return _history_turns_to_messages((summary.metadata_ or {}).get("history", []), max_turns)
    except Exception as e:
        logger.warning(f"Failed to load conversation history for rewrite: {e}")
        return []


def _resolve_owned_summary(
    existing: "ConversationSummary | None", tenant_id: str, api_key_id: str | None
) -> "ConversationSummary | None":
    """Ownership gate + legacy adoption shared by every ConversationSummary
    write path (the non-stream `query()` handler, `_persist_rag_conversation`,
    `_persist_agent_conversation`). Returns `existing` if the caller may
    write to it — adopting it in place first if it is a legacy row with no
    recorded `api_key_id` — or `None` if it must be treated as foreign (or
    doesn't exist).

    See `_load_conversation_history`'s docstring for why `api_key_id`
    (authenticated, unspoofable) is the ownership key, not `user_id`/
    X-User-ID. Adoption on write (not on read: see the docstring above) is
    safe because a legacy row could already be updated by any same-tenant
    caller before this function existed — no ownership check ran at all.
    Adopting the first authenticated writer is a strict improvement (durable
    ownership from this point on) with no larger blast radius than today.
    """
    if not existing or not api_key_id or existing.tenant_id != tenant_id:
        return None
    if existing.api_key_id and existing.api_key_id != api_key_id:
        return None
    if not existing.api_key_id:
        logger.info("Adopting legacy conversation summary %s for api_key %s", existing.id, api_key_id)
        existing.api_key_id = api_key_id
    return existing


@dataclass
class _StreamPrePhase:
    """Detached state passed from the short RLS phase to an SSE body."""

    agent_mode: bool
    generation_service: Any
    retrieval_result: Any | None
    prepared_generation: Any | None
    stream_user_id: str
    api_key_id: str | None
    tenant_config_snapshot: dict[str, Any]
    conversation_history: list[dict] | None = None


class _ScopedAgentRetrievalService:
    """Open one short RLS session for each agent retrieval-tool invocation."""

    def __init__(self, rls_context: RequestRlsContext):
        self._rls_context = rls_context

    async def retrieve(self, **kwargs):
        from src.amber_platform.composition_root import build_retrieval_service

        async with request_rls_session(self._rls_context) as session:
            return await build_retrieval_service(session).retrieve(**kwargs)


async def _persist_rag_conversation(
    rls_context: RequestRlsContext,
    conversation_id: str,
    tenant_id: str,
    stream_user_id: str,
    api_key_id: str | None,
    query: str,
    answer: str,
    sources: list[Any],
    quality: dict[str, Any] | None,
) -> None:
    """Fail softly, but always reload a threaded conversation under post-stream RLS."""
    try:
        from sqlalchemy.orm.attributes import flag_modified

        from src.core.generation.domain.memory_models import ConversationSummary

        summary_text = (
            "" if _looks_like_refusal(answer, sources) else answer[:200] + "..." if len(answer) > 200 else answer
        )
        title_text = query[:50] + "..." if len(query) > 50 else query
        routing = {"categories": ["Imported Docs"], "confidence": 1.0}

        async with request_rls_session(rls_context) as session:
            existing_summary = await session.get(ConversationSummary, conversation_id)
            # See _load_conversation_history's docstring for the ownership
            resolved = _resolve_owned_summary(existing_summary, tenant_id, api_key_id)
            if existing_summary and not resolved:
                logger.warning("Skipping foreign RAG conversation persistence: %s", conversation_id)
                return
            existing_summary = resolved
            if existing_summary:
                history = existing_summary.metadata_.get("history", [])
                history.append(
                    {
                        "query": query,
                        "answer": answer,
                        "sources": sources,
                        "quality_score": quality,
                        "routing_info": routing,
                        "timestamp": _utc_now_iso(),
                    }
                )
                existing_summary.metadata_["history"] = history
                existing_summary.metadata_["query"] = query
                existing_summary.metadata_["answer"] = answer
                existing_summary.metadata_["timestamp"] = _utc_now_iso()
                flag_modified(existing_summary, "metadata_")
                session.add(existing_summary)
                logger.info("Updated RAG conversation history: %s", existing_summary.id)
                return

            session.add(
                ConversationSummary(
                    id=conversation_id,
                    tenant_id=tenant_id,
                    user_id=stream_user_id,
                    api_key_id=api_key_id,
                    title=title_text,
                    summary=summary_text,
                    metadata_={
                        "query": query,
                        "answer": answer,
                        "sources": sources,
                        "model": "rag-default",
                        "mode": "rag",
                        "history": [
                            {
                                "query": query,
                                "answer": answer,
                                "sources": sources,
                                "quality_score": quality,
                                "routing_info": routing,
                                "timestamp": _utc_now_iso(),
                            }
                        ],
                    },
                )
            )
            logger.info("Saved RAG conversation history: %s", conversation_id)
    except Exception as e:
        logger.error("Failed to save RAG conversation history: %s", e)


async def _persist_agent_conversation(
    rls_context: RequestRlsContext,
    conversation_id: str,
    tenant_id: str,
    user_id: str,
    api_key_id: str | None,
    query: str,
    answer: str,
    sources: list[Any],
    tools_used: list[str],
) -> bool:
    """Persist an agent turn after the provider finishes, without cross-tenant writes."""
    try:
        from sqlalchemy.orm.attributes import flag_modified

        from src.core.generation.domain.memory_models import ConversationSummary

        summary_text = (
            "" if _looks_like_refusal(answer, sources) else answer[:200] + "..." if len(answer) > 200 else answer
        )
        title_text = query[:50] + "..." if len(query) > 50 else query
        async with request_rls_session(rls_context) as session:
            existing_summary = await session.get(ConversationSummary, conversation_id)
            resolved = _resolve_owned_summary(existing_summary, tenant_id, api_key_id)
            if existing_summary and not resolved:
                logger.warning("Skipping foreign agent conversation persistence: %s", conversation_id)
                return False
            existing_summary = resolved
            if existing_summary:
                history = existing_summary.metadata_.get("history", [])
                history.append(
                    {
                        "query": query,
                        "answer": answer,
                        "sources": sources,
                        "timestamp": _utc_now_iso(),
                    }
                )
                existing_summary.metadata_["history"] = history
                existing_summary.metadata_["query"] = query
                existing_summary.metadata_["answer"] = answer
                existing_summary.metadata_["sources"] = sources
                existing_summary.metadata_["timestamp"] = _utc_now_iso()
                flag_modified(existing_summary, "metadata_")
                session.add(existing_summary)
                logger.info("Updated AGENT conversation history: %s", existing_summary.id)
                return True

            session.add(
                ConversationSummary(
                    id=conversation_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    api_key_id=api_key_id,
                    title=title_text,
                    summary=summary_text,
                    metadata_={
                        "query": query,
                        "answer": answer,
                        "model": "agent-default",
                        "mode": "agent",
                        "tools_used": tools_used,
                        "history": [
                            {
                                "query": query,
                                "answer": answer,
                                "sources": sources,
                                "routing_info": {
                                    "categories": ["Agent Tools"],
                                    "confidence": 1.0,
                                },
                                "timestamp": _utc_now_iso(),
                            }
                        ],
                    },
                )
            )
            logger.info("Saved AGENT conversation history: %s", conversation_id)
            return True
    except Exception as e:
        logger.error("Failed to save AGENT conversation history: %s", e)
        return None


async def _prepare_stream_phase(
    http_request: Request,
    request: QueryRequest,
    rls_context: RequestRlsContext,
) -> _StreamPrePhase:
    """Run all request-DB work before waiting on an LLM provider."""
    import asyncio

    from src.amber_platform.composition_root import (
        build_generation_service,
        build_retrieval_service,
    )

    tenant_id = _get_tenant_id(http_request)
    stream_user_id = _get_user_id(http_request)
    api_key_id = _get_api_key_id(http_request)

    async with request_rls_session(rls_context) as session:
        generation_service = build_generation_service(session)

        # =========================================================================
        # STICKY MODE CHECK
        # =========================================================================
        # Check if this is a continuation of an AGENT conversation.
        if request.conversation_id and not (request.options and request.options.agent_mode):
            try:
                from src.core.generation.domain.memory_models import ConversationSummary

                existing_conv = await session.get(ConversationSummary, request.conversation_id)
                if existing_conv and existing_conv.metadata_:
                    # Ownership check: only allow sticky switch for caller's own conversation.
                    # api_key_id (unspoofable), not user_id/X-User-ID — see
                    # _load_conversation_history's docstring. A legacy
                    # conversation with no recorded api_key_id is treated as
                    # foreign here (read-only decision, no adoption): unlike
                    # the persistence functions, there is no write to anchor
                    # an adoption to.
                    if (
                        existing_conv.tenant_id != tenant_id
                        or not existing_conv.api_key_id
                        or existing_conv.api_key_id != api_key_id
                    ):
                        existing_conv = None  # ignore foreign conversations
                if existing_conv and existing_conv.metadata_:
                    mode = existing_conv.metadata_.get("mode")
                    if mode == "agent":
                        logger.info(
                            f"Auto-switching conversation {request.conversation_id} to Agent Mode (Sticky)"
                        )
                        if not request.options:
                            from src.api.schemas.query import QueryOptions

                            request.options = QueryOptions(agent_mode=True)
                        else:
                            request.options.agent_mode = True
            except Exception as e:
                logger.warning(f"Failed to check stickiness: {e}")

        if request.options and request.options.agent_mode:
            snapshot_getter = getattr(generation_service, "_get_effective_tenant_config", None)
            snapshot_result = snapshot_getter(tenant_id) if callable(snapshot_getter) else {}
            tenant_config_snapshot = (
                await snapshot_result if isawaitable(snapshot_result) else snapshot_result
            )
            agent_history: list[dict] | None = None
            from src.api.config import settings as history_settings

            if history_settings.enable_multiturn_history_reinjection:
                agent_history = await _load_conversation_history(
                    session, request.conversation_id, tenant_id, api_key_id
                )
            return _StreamPrePhase(
                agent_mode=True,
                generation_service=generation_service,
                retrieval_result=None,
                prepared_generation=None,
                stream_user_id=stream_user_id,
                api_key_id=api_key_id,
                tenant_config_snapshot=dict(tenant_config_snapshot or {}),
                conversation_history=agent_history,
            )

        retrieval_service = build_retrieval_service(session)
        document_ids = request.filters.document_ids if request.filters else None
        max_chunks = request.options.max_chunks if request.options else 10

        # Rate Limit Protection
        from src.core.admin_ops.application.tuning_service import TuningService
        from src.core.generation.application.llm_model_resolver import resolve_tenant_llm_model
        from src.core.generation.infrastructure.providers.openai import OpenAILLMProvider
        from src.shared.kernel.runtime import get_settings

        try:
            effective_model = request.options.model if request.options else None
            if not effective_model:
                settings = get_settings()
                tuning_service = TuningService(
                    session_factory=None,
                    redis_url=settings.db.redis_url,
                    session=session,
                )
                tenant_config = await tuning_service.get_effective_tenant_config(tenant_id)
                effective_model, _ = resolve_tenant_llm_model(
                    tenant_config,
                    settings,
                    context="query.rate_limit_clamp",
                    tenant_id=tenant_id,
                )

            if effective_model:
                model_cfg = OpenAILLMProvider.models.get(effective_model)
                if model_cfg:
                    model_limit = model_cfg.get("max_top_k")
                    if model_limit and max_chunks > model_limit:
                        logger.warning(
                            f"Clamping max_chunks from {max_chunks} to {model_limit} for model {effective_model}"
                        )
                        max_chunks = model_limit
        except Exception as e:
            logger.error(f"Failed to resolve effective model for rate limiting: {e}")

        conversation_history: list[dict] | None = None
        from src.api.config import settings as history_settings

        if history_settings.enable_multiturn_history_reinjection:
            conversation_history = await _load_conversation_history(
                session, request.conversation_id, tenant_id, api_key_id
            )

        try:
            retrieval_result = await asyncio.wait_for(
                retrieval_service.retrieve(
                    query=request.query,
                    tenant_id=tenant_id,
                    document_ids=document_ids,
                    top_k=max_chunks,
                    include_trace=request.options.include_trace if request.options else False,
                    options=request.options,
                    history=conversation_history or None,
                    query_scopes=getattr(http_request.state, "query_scopes", None),
                ),
                timeout=120.0,
            )
        except Exception as e:
            logger.error(f"Retrieval failed: {type(e).__name__}: {e}")
            from src.shared.error_handling import map_exception_to_error_data

            return _StreamPrePhase(
                agent_mode=False,
                generation_service=generation_service,
                retrieval_result=map_exception_to_error_data(e),
                prepared_generation=None,
                stream_user_id=stream_user_id,
                api_key_id=api_key_id,
                tenant_config_snapshot={},
                conversation_history=conversation_history,
            )

        if not retrieval_result.chunks:
            return _StreamPrePhase(
                agent_mode=False,
                generation_service=generation_service,
                retrieval_result=retrieval_result,
                prepared_generation=None,
                stream_user_id=stream_user_id,
                api_key_id=api_key_id,
                tenant_config_snapshot={},
                conversation_history=conversation_history,
            )

        prepare_stream = getattr(generation_service, "prepare_stream", None)
        prepared_generation = None
        if callable(prepare_stream):
            prepared_generation = await prepare_stream(
                query=request.query,
                candidates=retrieval_result.chunks,
                conversation_history=conversation_history or None,
                options={
                    "user_id": stream_user_id,
                    "tenant_id": tenant_id,
                    "model": request.options.model if request.options else None,
                },
                session=session,
            )

        return _StreamPrePhase(
            agent_mode=False,
            generation_service=generation_service,
            retrieval_result=retrieval_result,
            prepared_generation=prepared_generation,
            stream_user_id=stream_user_id,
            api_key_id=api_key_id,
            tenant_config_snapshot={},
            conversation_history=conversation_history,
        )


# =============================================================================
# Streaming Endpoint
# =============================================================================


async def _query_stream_impl(
    http_request: Request,
    request: QueryRequest = None,
    query: str = None,
    agent_mode: bool = False,
    model: str = None,
    conversation_id: str = None,
):
    """Stream a query while bounding request-RLS sessions to DB-only phases."""

    if http_request.method == "GET":
        if not query:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Query parameter 'query' is required for GET requests",
            )
        from src.api.schemas.query import QueryOptions

        request = QueryRequest(
            query=query,
            options=QueryOptions(agent_mode=agent_mode, model=model),
            conversation_id=conversation_id,
        )

    if request is None:
        raise HTTPException(status_code=400, detail="Invalid request")

    tenant_id = _get_tenant_id(http_request)
    rls_context = get_request_rls_context(http_request)
    logger.info("SSE stream request: query=%s..., tenant=%s", request.query[:50], tenant_id)

    async def generate_stream():
        padding_token = "abcdefghijklmnopqrstuvwxyz1234567890!@#$%^&*()_+[]{};'.,<>?"
        yield f": {(padding_token * 100)[:4096]}\n\n"
        yield f"event: status\ndata: {json.dumps('Searching documents...')}\n\n"

        try:
            # List/count queries do not use the SQLAlchemy stream phases.
            stream_scopes = getattr(http_request.state, "query_scopes", None)
            structured_allowed = not getattr(stream_scopes, "enforce_groups", False)
            if not structured_allowed:
                logger.debug(
                    "SSE: structured fast-path skipped (group enforcement active) tenant=%s",
                    tenant_id,
                )
            try:
                from src.core.retrieval.application.query.structured_query import (
                    structured_executor,
                )

                structured_result = (
                    await structured_executor.try_execute(query=request.query, tenant_id=tenant_id)
                    if structured_allowed
                    else None
                )
                if structured_result and structured_result.success:
                    payload = {
                        "query_type": structured_result.query_type.value,
                        "data": structured_result.data,
                        "count": structured_result.count,
                        "timing": {
                            "total_ms": round(structured_result.execution_time_ms, 2),
                            "retrieval_ms": round(structured_result.execution_time_ms, 2),
                            "generation_ms": 0,
                        },
                    }
                    yield f"event: structured_result\ndata: {json.dumps(payload)}\n\n"
                    yield f"event: done\ndata: {json.dumps('[DONE]')}\n\n"
                    return
            except Exception as exc:
                logger.debug("SSE: structured query check failed, continuing to RAG/agent: %s", exc)

            phase = await _prepare_stream_phase(http_request, request, rls_context)

            if phase.agent_mode:
                from fastapi import HTTPException as FastAPIHTTPException

                from src.api.config import settings as stream_settings

                if not stream_settings.enable_agent_mode:
                    raise FastAPIHTTPException(status_code=403, detail="Agent mode is disabled on this server.")
                agent_role = request.options.agent_role if request.options else "knowledge"
                if agent_role == "maintainer" and not getattr(
                    http_request.state, "is_super_admin", False
                ):
                    raise FastAPIHTTPException(
                        status_code=403,
                        detail="agent_role='maintainer' requires super_admin privileges.",
                    )

                import uuid

                from src.amber_platform.composition_root import build_generation_service
                from src.core.generation.application.agent.orchestrator import AgentOrchestrator
                from src.core.generation.application.agent.prompts import AGENT_SYSTEM_PROMPT
                from src.core.tools.filesystem import create_filesystem_tools
                from src.core.tools.retrieval import create_retrieval_tool

                yield (
                    "event: status\ndata: "
                    f"{json.dumps('Consulting agent tools (Mail, Calendar, etc.)...')}\n\n"
                )
                agent_conversation_id = request.conversation_id or str(uuid.uuid4())
                yield f"event: conversation_id\ndata: {json.dumps(agent_conversation_id)}\n\n"
                yield (
                    "event: routing\ndata: "
                    f"{json.dumps({'categories': ['Agent Tools'], 'confidence': 1.0})}\n\n"
                )

                # A fresh service has no request session.  It receives only the
                # preloaded tenant configuration, so provider waits retain no DB
                # checkout from the pre-phase.
                generation_service = build_generation_service(None)
                set_snapshot = getattr(generation_service, "set_tenant_config_snapshot", None)
                if callable(set_snapshot):
                    set_snapshot(phase.tenant_config_snapshot)

                retrieval_tool_def = create_retrieval_tool(
                    _ScopedAgentRetrievalService(rls_context),
                    tenant_id,
                    query_scopes=getattr(http_request.state, "query_scopes", None),
                )
                tool_map = {retrieval_tool_def["name"]: retrieval_tool_def["func"]}
                tool_schemas = [retrieval_tool_def["schema"]]
                if agent_role == "maintainer" and stream_settings.enable_maintainer_tools:
                    for tool in create_filesystem_tools(base_path="."):
                        tool_map[tool["name"]] = tool["func"]
                        tool_schemas.append(tool["schema"])
                elif stream_settings.enable_agent_graph_tool:
                    from src.core.tools.graph import create_graph_tool

                    graph_tool = create_graph_tool(tenant_id)
                    tool_map["query_graph"] = graph_tool["func"]
                    tool_schemas.append(graph_tool["schema"])

                agent = AgentOrchestrator(
                    generation_service=generation_service,
                    tools=tool_map,
                    tool_schemas=tool_schemas,
                    system_prompt=AGENT_SYSTEM_PROMPT,
                )
                agent_response = await agent.run(
                    query=request.query,
                    conversation_id=agent_conversation_id,
                    conversation_history=phase.conversation_history,
                )
                agent_sources = getattr(agent_response, "sources", []) or []
                agent_trace = getattr(agent_response, "trace", []) or []
                tools_actually_called = list(
                    dict.fromkeys(
                        step["step"].split(":", 1)[1]
                        for step in agent_trace
                        if isinstance(step, dict) and step.get("step", "").startswith("tool_call:")
                    )
                )

                persisted = await _persist_agent_conversation(
                    rls_context=rls_context,
                    conversation_id=agent_conversation_id,
                    tenant_id=tenant_id,
                    user_id=phase.stream_user_id,
                    api_key_id=phase.api_key_id,
                    query=request.query,
                    answer=agent_response.answer,
                    sources=agent_sources,
                    tools_used=tools_actually_called,
                )
                if persisted is False:
                    yield f"event: error\ndata: {json.dumps('Conversation not found')}\n\n"
                    return

                answer_text = agent_response.answer or ""
                for chunk in re.findall(r"\S+|\s+", answer_text):
                    yield f"event: token\ndata: {json.dumps(chunk)}\n\n"
                yield f"event: message\ndata: {json.dumps(answer_text)}\n\n"
                yield f"event: done\ndata: {json.dumps('[DONE]')}\n\n"
                return

            retrieval_result = phase.retrieval_result
            if isinstance(retrieval_result, dict):
                yield f"event: processing_error\ndata: {json.dumps(retrieval_result)}\n\n"
                return
            if not retrieval_result.chunks:
                yield f"data: {json.dumps('No relevant documents found.')}\n\n"
                yield f"event: done\ndata: {json.dumps('[DONE]')}\n\n"
                return

            yield (
                "event: routing\ndata: "
                f"{json.dumps({'categories': ['Imported Docs'], 'confidence': 1.0})}\n\n"
            )
            quality_data = _build_quality_data(retrieval_result.chunks)
            yield f"event: quality\ndata: {json.dumps(quality_data)}\n\n"

            import uuid

            final_conversation_id = request.conversation_id or str(uuid.uuid4())
            yield f"event: conversation_id\ndata: {json.dumps(final_conversation_id)}\n\n"

            full_answer = ""
            collected_sources: list[Any] = []
            stream_model = ""
            stream_provider = ""
            stream_start_time = time.perf_counter()

            def process_stream_event(event_dict: dict[str, Any]) -> tuple[str, Any]:
                nonlocal collected_sources, full_answer, stream_model, stream_provider

                event = event_dict.get("event", "message")
                data = event_dict.get("data", "")
                if event == "token":
                    full_answer += str(data)
                elif event == "sources":
                    collected_sources = data
                elif event == "done" and isinstance(data, dict):
                    stream_model = data.get("model", "")
                    stream_provider = data.get("provider", "")
                return event, data

            if phase.prepared_generation is not None:
                for event_dict in phase.prepared_generation.prelude_events:
                    event, data = process_stream_event(event_dict)
                    yield f"event: {event}\ndata: {json.dumps(data)}\n\n"
                event_iterator = phase.generation_service.stream_prepared(
                    phase.prepared_generation
                )
            else:
                event_iterator = phase.generation_service.generate_stream(
                    query=request.query,
                    candidates=retrieval_result.chunks,
                    conversation_history=phase.conversation_history or None,
                    options={
                        "user_id": phase.stream_user_id,
                        "tenant_id": tenant_id,
                        "model": request.options.model if request.options else None,
                    },
                )

            async for event_dict in event_iterator:
                event, data = process_stream_event(event_dict)
                yield f"event: {event}\ndata: {json.dumps(data)}\n\n"

            full_answer = phase.generation_service._normalize_citations(full_answer)
            stream_latency_ms = (time.perf_counter() - stream_start_time) * 1000
            persistence_quality = _build_quality_data(retrieval_result.chunks)
            await _persist_rag_conversation(
                rls_context=rls_context,
                conversation_id=final_conversation_id,
                tenant_id=tenant_id,
                stream_user_id=phase.stream_user_id,
                api_key_id=phase.api_key_id,
                query=request.query,
                answer=full_answer,
                sources=collected_sources,
                quality=persistence_quality,
            )

            # Context graph and operational metrics are fail-soft external work.
            try:
                import asyncio

                from src.core.graph.application.context_writer import context_graph_writer

                asyncio.create_task(
                    context_graph_writer.log_turn(
                        conversation_id=final_conversation_id,
                        tenant_id=tenant_id,
                        query=request.query,
                        answer=full_answer,
                        sources=_build_graph_sources(collected_sources),
                        model=stream_model,
                        latency_ms=stream_latency_ms,
                    )
                )
            except Exception as exc:
                logger.warning("Failed to schedule context graph logging for stream: %s", exc)

            try:
                from src.api.config import settings
                from src.core.admin_ops.application.metrics.collector import (
                    MetricsCollector,
                    QueryMetrics,
                )
                from src.core.utils.tokenizer import Tokenizer
                from src.shared.identifiers import generate_query_id
                from src.shared.model_registry import LLM_MODELS

                query_id = generate_query_id()
                output_tokens = Tokenizer.count_tokens(full_answer, stream_model)
                chunk_text = (
                    "\n".join(getattr(chunk, "content", "") for chunk in retrieval_result.chunks)
                    if retrieval_result.chunks
                    else ""
                )
                input_tokens = Tokenizer.count_tokens(f"{request.query}\n{chunk_text}", stream_model)

                pricing = {"input": 0.00015, "output": 0.0006}
                model_cfg = LLM_MODELS.get(stream_provider, {}).get(stream_model)
                if model_cfg:
                    pricing = {
                        "input": model_cfg.get("input_cost_per_1k", pricing["input"]),
                        "output": model_cfg.get("output_cost_per_1k", pricing["output"]),
                    }
                cost_estimate = (input_tokens * pricing["input"] / 1000) + (
                    output_tokens * pricing["output"] / 1000
                )
                metrics = QueryMetrics(
                    query_id=query_id,
                    tenant_id=tenant_id,
                    query=request.query,
                    operation="rag_query",
                    response=full_answer[:500],
                    chunks_retrieved=len(retrieval_result.chunks),
                    chunks_used=len(retrieval_result.chunks),
                    cache_hit=retrieval_result.cache_hit,
                    tokens_used=input_tokens + output_tokens,
                    output_tokens=output_tokens,
                    generation_latency_ms=stream_latency_ms,
                    total_latency_ms=stream_latency_ms,
                    cost_estimate=cost_estimate,
                    model=stream_model,
                    provider=stream_provider or "unknown",
                    success=True,
                    conversation_id=final_conversation_id,
                    sources_cited=len(collected_sources),
                    answer_length=len(full_answer),
                )
                collector = MetricsCollector(redis_url=settings.db.redis_url)
                await collector.record(metrics)
                await collector.close()
                logger.debug("Recorded streaming metrics for query %s", query_id)
            except Exception as exc:
                logger.warning("Failed to record streaming metrics: %s", exc)

            yield f"event: done\ndata: {json.dumps('[DONE]')}\n\n"
        except Exception as exc:
            error_code = "error"
            provider = "System"
            message = str(exc)
            is_handled_error = False

            def get_provider(error: Exception) -> str:
                return error.provider.title() if getattr(error, "provider", None) else "Provider"

            try:
                from src.core.generation.domain.provider_models import (
                    AuthenticationError,
                    InvalidRequestError,
                    ProviderUnavailableError,
                    RateLimitError,
                )

                if isinstance(exc, RateLimitError):
                    error_code, provider, is_handled_error = "rate_limit", get_provider(exc), True
                elif isinstance(exc, AuthenticationError):
                    error_code, provider, message, is_handled_error = (
                        "auth_error",
                        get_provider(exc),
                        "Authentication failed",
                        True,
                    )
                elif isinstance(exc, InvalidRequestError):
                    error_code, provider, message, is_handled_error = (
                        "context_length" if "context" in str(exc).lower() else "invalid_request",
                        get_provider(exc),
                        "Invalid request",
                        True,
                    )
                elif isinstance(exc, ProviderUnavailableError):
                    error_code, provider, message, is_handled_error = (
                        "provider_error",
                        get_provider(exc),
                        "Service unavailable",
                        True,
                    )
            except ImportError:
                error_name = type(exc).__name__
                if "RateLimitError" in error_name:
                    error_code, is_handled_error = "rate_limit", True
                elif "AuthenticationError" in error_name:
                    error_code, is_handled_error = "auth_error", True
                elif "InvalidRequestError" in error_name:
                    error_code = "context_length" if "context" in str(exc).lower() else "invalid_request"
                    is_handled_error = True
                elif "ProviderUnavailableError" in error_name:
                    error_code, is_handled_error = "provider_error", True
                if is_handled_error and getattr(exc, "provider", None):
                    provider = exc.provider.title()

            if is_handled_error:
                logger.warning("Handled provider error: %s from %s - %s", error_code, provider, exc)
                yield (
                    "event: processing_error\ndata: "
                    f"{json.dumps({'code': error_code, 'message': message, 'provider': provider})}\n\n"
                )
                return

            logger.exception("Stream generation failed: %s", exc)
            yield f"event: processing_error\ndata: {json.dumps(str(exc))}\n\n"

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Encoding": "none",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/stream",
    summary="Stream Query Response",
    description="Stream the query response using Server-Sent Events.",
    operation_id="query_stream_get",
)
async def query_stream_get(
    http_request: Request,
    query: str,
    agent_mode: bool = False,
    model: str = None,  # Added model param
    conversation_id: str = None,
):
    return await _query_stream_impl(
        http_request=http_request,
        request=None,
        query=query,
        agent_mode=agent_mode,
        model=model,  # Pass model param
        conversation_id=conversation_id,
    )


@router.post(
    "/stream",
    summary="Stream Query Response",
    description="Stream the query response using Server-Sent Events.",
    operation_id="query_stream_post",
)
async def query_stream_post(
    http_request: Request,
    request: QueryRequest,
):
    return await _query_stream_impl(
        http_request=http_request,
        request=request,
    )
