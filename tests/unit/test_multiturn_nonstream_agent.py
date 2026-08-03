"""
Unit tests for Issue #30: Multi-turn history re-injection for non-stream & agent paths.

Covers:
1. QueryUseCase.execute passes conversation_history to retrieve() and generate().
2. QueryUseCase._execute_agent passes conversation_history to agent.run().
3. query.py stream agent path passes phase.conversation_history to agent.run().
4. GenerationService.generate forwards conversation_history to provider.generate(history=...).
5. OpenAILLMProvider.generate & OllamaLLMProvider.generate accept history and prepend it to messages.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.config import settings as api_settings
from src.core.generation.application.generation_service import GenerationResult, GenerationService
from src.core.generation.domain.provider_models import (
    GenerationResult as ProviderGenerationResult,
    ProviderConfig,
    TokenUsage,
)
from src.core.generation.infrastructure.providers.ollama import OllamaLLMProvider
from src.core.generation.infrastructure.providers.openai import OpenAILLMProvider
from src.core.retrieval.application.use_cases_query import QueryUseCase
from src.api.schemas.query import QueryOptions, QueryRequest
from src.shared.kernel.runtime import configure_settings


@pytest.fixture(autouse=True)
def setup_settings():
    configure_settings(api_settings)


@pytest.mark.asyncio
async def test_query_use_case_execute_forwards_history_to_retrieve_and_generate():
    """QueryUseCase.execute must forward conversation_history to both retrieve() and generate()."""
    retrieval_service = MagicMock()
    retrieval_service.retrieve = AsyncMock(
        return_value=SimpleNamespace(
            chunks=[{"chunk_id": "c1", "content": "text", "score": 0.9, "title": "Doc 1"}],
            cache_hit=False,
            search_mode="basic",
            router_latency_ms=1.0,
            trace=[],
        )
    )

    generation_service = MagicMock()
    generation_service.generate = AsyncMock(
        return_value=GenerationResult(
            answer="Answer",
            sources=[SimpleNamespace(document_id="d1", title="Doc 1", content_preview="text", score=0.9)],
            model="gpt-4o",
            provider="openai",
            latency_ms=1.0,
            tokens_used=10,
            cost_estimate=0.0,
            follow_up_questions=[],
            trace=[],
        )
    )

    metrics_collector = MagicMock()
    metrics_collector.track_query = MagicMock()

    class FakeTrackQuery:
        async def __aenter__(self):
            return SimpleNamespace()

        async def __aexit__(self, *args):
            return False

    metrics_collector.track_query.return_value = FakeTrackQuery()

    uc = QueryUseCase(
        retrieval_service=retrieval_service,
        generation_service=generation_service,
        metrics_collector=metrics_collector,
    )

    req = QueryRequest(query="What about limits?", conversation_id="conv-123")
    history = [{"role": "user", "content": "Tell me about UMR"}]

    await uc.execute(
        request=req,
        tenant_id="tenant-1",
        user_id="user-1",
        conversation_history=history,
    )

    # Check retrieve() call
    retrieval_service.retrieve.assert_called_once()
    assert retrieval_service.retrieve.call_args.kwargs.get("history") == history

    # Check generate() call
    generation_service.generate.assert_called_once()
    assert generation_service.generate.call_args.kwargs.get("conversation_history") == history


@pytest.mark.asyncio
async def test_query_use_case_execute_agent_forwards_history():
    """QueryUseCase._execute_agent must pass conversation_history to AgentOrchestrator.run()."""
    retrieval_service = MagicMock()
    generation_service = MagicMock()
    metrics_collector = MagicMock()

    uc = QueryUseCase(
        retrieval_service=retrieval_service,
        generation_service=generation_service,
        metrics_collector=metrics_collector,
    )

    req = QueryRequest(
        query="Agent question",
        conversation_id="conv-agent",
        options=QueryOptions(agent_mode=True),
    )
    history = [{"role": "user", "content": "Prior turn"}]

    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(
        return_value=SimpleNamespace(
            answer="Agent response",
            sources=[],
            conversation_id="conv-agent",
        )
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "src.core.generation.application.agent.orchestrator.AgentOrchestrator",
            lambda **kwargs: mock_agent,
        )
        mp.setattr(
            "src.core.retrieval.application.use_cases_query._agent_flag",
            lambda flag: True,
        )

        await uc.execute(
            request=req,
            tenant_id="tenant-1",
            user_id="user-1",
            conversation_history=history,
        )

    mock_agent.run.assert_called_once()
    assert mock_agent.run.call_args.kwargs.get("conversation_history") == history


@pytest.mark.asyncio
async def test_generation_service_generate_forwards_history_to_provider():
    """GenerationService.generate must forward conversation_history to provider.generate(history=...)."""
    svc = object.__new__(GenerationService)
    svc.config = SimpleNamespace(
        max_context_tokens=1000,
        model="gpt-4o",
        prompt_version="v1",
        temperature=0.7,
        seed=None,
        tier="default",
        max_tokens=500,
        enable_follow_up=False,
    )
    svc.registry = MagicMock()
    svc.registry.get_prompt = MagicMock(return_value="Prompt template")
    svc.llm = MagicMock()
    svc.llm.model_name = "gpt-4o"
    svc._get_effective_tenant_config = AsyncMock(return_value={})
    svc._resolve_provider_factory = MagicMock(return_value=None)
    svc._apply_complexity_routing = lambda **kwargs: (kwargs["llm_cfg"], "standard", False)
    svc._get_document_titles = AsyncMock(return_value={})
    svc._map_sources = MagicMock(return_value=[])

    mock_provider = MagicMock()
    mock_provider.generate = AsyncMock(
        return_value=ProviderGenerationResult(
            text="Provider response",
            provider="openai",
            model="gpt-4o",
            usage=TokenUsage(10, 5),
        )
    )
    svc.llm = mock_provider

    history = [{"role": "user", "content": "Prior message"}]
    await svc.generate(
        query="Current query",
        candidates=[{"chunk_id": "c1", "content": "chunk text", "metadata": {}}],
        conversation_history=history,
    )

    mock_provider.generate.assert_called_once()
    assert mock_provider.generate.call_args.kwargs.get("history") == history


@pytest.mark.asyncio
async def test_openai_provider_generate_prepends_history_to_messages(monkeypatch):
    """OpenAILLMProvider.generate must prepend history messages before the user prompt."""
    provider = OpenAILLMProvider(config=ProviderConfig(api_key="test-key"))
    provider.default_model = "gpt-4o"

    captured_messages = []

    async def fake_create(**kwargs):
        captured_messages.extend(kwargs.get("messages", []))
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content="Answer"), finish_reason="stop")]
        mock_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
        return mock_resp

    monkeypatch.setattr(provider.client.chat.completions, "create", fake_create)

    history = [
        {"role": "user", "content": "Turn 1 Q"},
        {"role": "assistant", "content": "Turn 1 A"},
    ]

    await provider.generate(
        prompt="Turn 2 Q",
        system_prompt="System prompt",
        history=history,
    )

    assert len(captured_messages) == 4
    assert captured_messages[0] == {"role": "system", "content": "System prompt"}
    assert captured_messages[1] == {"role": "user", "content": "Turn 1 Q"}
    assert captured_messages[2] == {"role": "assistant", "content": "Turn 1 A"}
    assert captured_messages[3] == {"role": "user", "content": "Turn 2 Q"}


@pytest.mark.asyncio
async def test_ollama_provider_generate_prepends_history_to_messages(monkeypatch):
    """OllamaLLMProvider.generate must prepend history messages before the user prompt."""
    provider = OllamaLLMProvider(
        config=ProviderConfig(base_url="http://localhost:11434"),
        use_capacity_limiter=False,
    )
    provider.default_model = "llama3"

    captured_messages = []

    async def fake_create(**kwargs):
        captured_messages.extend(kwargs.get("messages", []))
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content="Answer"), finish_reason="stop")]
        mock_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
        return mock_resp

    monkeypatch.setattr(provider.client.chat.completions, "create", fake_create)

    history = [
        {"role": "user", "content": "Turn 1 Q"},
        {"role": "assistant", "content": "Turn 1 A"},
    ]

    await provider.generate(
        prompt="Turn 2 Q",
        system_prompt="System prompt",
        history=history,
    )

    assert len(captured_messages) == 4
    assert captured_messages[0] == {"role": "system", "content": "System prompt"}
    assert captured_messages[1] == {"role": "user", "content": "Turn 1 Q"}
    assert captured_messages[2] == {"role": "assistant", "content": "Turn 1 A"}
    assert captured_messages[3] == {"role": "user", "content": "Turn 2 Q"}


@pytest.mark.asyncio
async def test_nonstream_query_route_loads_history_with_api_key_id(monkeypatch):
    """The non-stream `query()` handler must invoke `_load_conversation_history` with
    the authenticated `api_key_id`, never with `X-User-ID` (caller-controlled, spoofable
    — see issue #72). A caller who sets `X-User-ID` to a victim's identity must not
    gain access to that victim's conversation history through this call-site."""
    from src.api.routes.query import query

    loaded_calls = []

    async def fake_load_conversation_history(session, conv_id, tenant_id, api_key_id):
        loaded_calls.append({"conv_id": conv_id, "tenant_id": tenant_id, "api_key_id": api_key_id})
        return [{"role": "user", "content": "previous turn"}]

    monkeypatch.setattr("src.api.routes.query._load_conversation_history", fake_load_conversation_history)

    executed_calls = []

    async def fake_execute(self, request, tenant_id, http_request_state=None, user_id="", conversation_history=None):
        executed_calls.append({"user_id": user_id, "history": conversation_history})
        return SimpleNamespace(
            conversation_id="conv-100",
            answer="Answer text",
            sources=[],
        )

    monkeypatch.setattr("src.core.retrieval.application.use_cases_query.QueryUseCase.execute", fake_execute)
    monkeypatch.setattr("src.amber_platform.composition_root.build_retrieval_service", lambda _s: MagicMock())
    monkeypatch.setattr("src.amber_platform.composition_root.build_generation_service", lambda _s: MagicMock())
    monkeypatch.setattr("src.amber_platform.composition_root.build_metrics_collector", lambda: MagicMock())

    from src.api.config import settings as api_settings
    monkeypatch.setattr(api_settings, "enable_multiturn_history_reinjection", True, raising=False)

    mock_request = SimpleNamespace(
        method="POST",
        state=SimpleNamespace(tenant_id="tenant-xyz", api_key_name="my-key-name", api_key_id="key-id-999"),
        # A caller-controlled header. If ownership were ever gated on this again
        # (the #72 regression), this test would still pass "resolved-user-id"
        # through and the assertion below on api_key_id would catch it.
        headers={"X-User-ID": "resolved-user-id"},
    )
    query_body = QueryRequest(query="Follow-up query", conversation_id="conv-100")
    mock_session = AsyncMock()

    response = await query(request=query_body, http_request=mock_request, session=mock_session)

    assert len(loaded_calls) == 1
    assert loaded_calls[0]["api_key_id"] == "key-id-999"
    assert loaded_calls[0]["conv_id"] == "conv-100"
    assert len(executed_calls) == 1
    assert executed_calls[0]["history"] == [{"role": "user", "content": "previous turn"}]
