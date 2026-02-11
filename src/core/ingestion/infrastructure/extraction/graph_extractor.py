import json
import logging
import time
from pathlib import Path
from typing import Any

from src.core.generation.application.prompts.entity_extraction import (
    ExtractionResult,  # We keep this for external compat types if needed
    get_gleaning_prompt,
    get_tuple_extraction_prompt,
)
from src.core.generation.infrastructure.providers.base import ProviderTier
from src.core.generation.infrastructure.providers.factory import get_llm_provider
from src.core.graph.application.sync_config import (
    GraphSyncRuntimeConfig,
    resolve_graph_sync_runtime_config,
)
from src.core.graph.domain.models import Entity, Relationship
from src.core.ingestion.infrastructure.extraction.extraction_cache import (
    ExtractionCache,
    ExtractionCacheConfig,
)
from src.core.ingestion.infrastructure.extraction.tuple_parser import TupleParser

logger = logging.getLogger(__name__)


class GraphExtractor:
    """
    Service to extract Knowledge Graph elements (Entities, Relationships) from text
    using robust Tuple Parser and Dynamic Ontology injection.
    """

    def __init__(self, use_gleaning: bool = True, max_gleaning_steps: int = 1):
        self.use_gleaning = use_gleaning
        self.max_gleaning_steps = max_gleaning_steps
        self.entity_types, self.relationship_suggestions = self._load_config()
        self.parser = TupleParser()
        self._cache: ExtractionCache | None = None
        self._cache_redis_url: str | None = None
        self._cache_ttl_seconds: int | None = None

    def _load_config(self) -> tuple[list[str], list[str]]:
        """Load entity and relationship types from JSON config."""
        try:
            config_path = Path("src/config/classification_config.json")
            if not config_path.exists():
                # Fallback to defaults if file missing
                return (["CONCEPT", "ENTITY"], ["RELATED_TO"])

            with open(config_path, encoding="utf-8") as f:
                data = json.load(f)
                return (
                    data.get("entity_types", ["CONCEPT"]),
                    data.get("relationship_suggestions", ["RELATED_TO"]),
                )
        except Exception as e:
            logger.error(f"Failed to load classification config: {e}")
            return (["CONCEPT"], ["RELATED_TO"])

    def _get_cache_client(
        self,
        *,
        redis_url: str,
        ttl_seconds: int,
        enabled: bool,
    ) -> ExtractionCache:
        if (
            self._cache is None
            or self._cache_redis_url != redis_url
            or self._cache_ttl_seconds != ttl_seconds
            or self._cache.config.enabled != enabled
        ):
            self._cache = ExtractionCache(
                ExtractionCacheConfig(
                    redis_url=redis_url,
                    ttl_seconds=ttl_seconds,
                    enabled=enabled,
                )
            )
            self._cache_redis_url = redis_url
            self._cache_ttl_seconds = ttl_seconds
        return self._cache

    def _should_run_gleaning(
        self,
        *,
        runtime_config: GraphSyncRuntimeConfig,
        text: str,
        entity_count: int,
        relationship_count: int,
    ) -> tuple[bool, str]:
        if not (self.use_gleaning and runtime_config.use_gleaning):
            return False, "gleaning_disabled"

        if self.max_gleaning_steps <= 0 or runtime_config.max_gleaning_steps <= 0:
            return False, "gleaning_steps_disabled"

        if not runtime_config.smart_gleaning_enabled:
            return True, "always_on"

        if (
            len(text) < runtime_config.smart_gleaning_min_chunk_chars
            and entity_count >= runtime_config.smart_gleaning_entity_threshold
        ):
            return False, "short_chunk_sufficient_entities"

        if entity_count < runtime_config.smart_gleaning_entity_threshold:
            return True, "low_entity_yield"

        if relationship_count < runtime_config.smart_gleaning_relationship_threshold:
            return True, "low_relationship_yield"

        return False, "sufficient_pass1_yield"

    async def extract(
        self,
        text: str,
        chunk_id: str = "UNKNOWN",
        track_usage: bool = True,
        tenant_id: str | None = None,
        tenant_config: dict[str, Any] | None = None,
        chunk_number: int | None = None,
        total_chunks: int | None = None,
    ) -> ExtractionResult:
        """
        Extract entities/relationships using tuple format + quality scoring.
        """
        # 1. Prepare Provider + step config
        from src.core.generation.application.llm_steps import resolve_llm_step_config

        tenant_config = tenant_config or {}
        from src.shared.context import get_current_tenant
        from src.shared.kernel.runtime import get_settings

        settings = get_settings()
        runtime_config = resolve_graph_sync_runtime_config(
            settings=settings,
            tenant_config=tenant_config,
        )
        llm_config = resolve_llm_step_config(
            tenant_config=tenant_config,
            step_id="ingestion.graph_extraction",
            settings=settings,
        )

        provider = get_llm_provider(
            provider_name=llm_config.provider,
            model=llm_config.model,
            tier=ProviderTier.ECONOMY,
        )

        # 2. Initial Pass (Pass 1)
        initial_prompt = get_tuple_extraction_prompt(
            self.entity_types, self.relationship_suggestions, text_unit_id=chunk_id
        )
        full_text_prompt = (
            f"{initial_prompt}\n\n**Text to analyze**:\n{text}\n\n**Output (tuple format only)**:"
        )

        all_entities: list[Entity] = []
        all_relationships: list[Relationship] = []

        # Usage tracking
        from src.core.generation.application.prompts.entity_extraction import ExtractionUsage

        usage_stats = ExtractionUsage()
        usage_stats.model = llm_config.model
        usage_stats.provider = llm_config.provider

        # Metrics tracking context
        from src.core.admin_ops.application.metrics.collector import MetricsCollector
        from src.shared.identifiers import generate_query_id

        query_id = generate_query_id()
        collector = MetricsCollector(redis_url=settings.db.redis_url)
        effective_tenant_id = tenant_id or get_current_tenant() or "system"
        progress_fields: dict[str, Any] = {}
        if chunk_number is not None:
            progress_fields["chunk_number"] = chunk_number
        if total_chunks is not None:
            progress_fields["total_chunks"] = total_chunks
        if chunk_number is not None and total_chunks is not None:
            progress_fields["chunk_progress"] = f"{chunk_number}/{total_chunks}"
        response: Any = None
        gleaning_steps_run = 0
        gleaning_run_reason = "not_applicable"
        gleaning_skip_reason = "not_applicable"

        # Optional extraction cache
        cache_key = None
        if runtime_config.cache_enabled:
            cache = self._get_cache_client(
                redis_url=settings.db.redis_url,
                ttl_seconds=runtime_config.cache_ttl_hours * 3600,
                enabled=True,
            )
            cache_key = ExtractionCache.build_cache_key(
                tenant_id=effective_tenant_id,
                text=text,
                prompt=initial_prompt,
                ontology={
                    "entity_types": self.entity_types,
                    "relationship_suggestions": self.relationship_suggestions,
                },
                model=llm_config.model,
                temperature=llm_config.temperature,
                seed=llm_config.seed,
                gleaning_mode=(
                    f"use={self.use_gleaning and runtime_config.use_gleaning};"
                    f"max={min(self.max_gleaning_steps, runtime_config.max_gleaning_steps)};"
                    f"smart={runtime_config.smart_gleaning_enabled};"
                    f"e={runtime_config.smart_gleaning_entity_threshold};"
                    f"r={runtime_config.smart_gleaning_relationship_threshold};"
                    f"chars={runtime_config.smart_gleaning_min_chunk_chars}"
                ),
            )

            cached_result = await cache.get(cache_key)
            if cached_result is not None:
                usage_stats.cache_hit = True
                logger.info(
                    "graph_extractor_chunk_metrics %s",
                    json.dumps(
                        {
                            "event": "graph_extractor_chunk_metrics",
                            "chunk_id": chunk_id,
                            "tenant_id": effective_tenant_id,
                            **progress_fields,
                            "cache_hit": True,
                            "gleaning_enabled": self.use_gleaning and runtime_config.use_gleaning,
                            "gleaning_steps_run": 0,
                            "gleaning_run_reason": "cache_hit",
                            "gleaning_skip_reason": "cache_hit",
                            "llm_calls": 0,
                            "tokens_total": 0,
                            "entities": len(cached_result.entities),
                            "relationships": len(cached_result.relationships),
                        },
                        sort_keys=True,
                    ),
                )
                return ExtractionResult(
                    entities=cached_result.entities,
                    relationships=cached_result.relationships,
                    usage=usage_stats,
                )

        try:
            # Helper to run generation and capture stats
            async def run_generation(prompt: str, temp: float, stage: str) -> Any:
                import hashlib

                prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:8]
                logger.debug(
                    f"[DET] run_generation: seed={llm_config.seed}, temp={temp}, prompt_hash={prompt_hash}"
                )

                started = time.perf_counter()
                response = await provider.generate(
                    prompt=prompt, temperature=temp, seed=llm_config.seed
                )
                latency_ms = int((time.perf_counter() - started) * 1000)

                # Accumulate stats
                if hasattr(response, "usage"):
                    usage_stats.total_tokens += response.usage.total_tokens
                    usage_stats.input_tokens += response.usage.input_tokens
                    usage_stats.output_tokens += response.usage.output_tokens

                if hasattr(response, "cost_estimate"):
                    usage_stats.cost_estimate += response.cost_estimate

                usage_stats.llm_calls += 1
                usage_stats.model = str(response.model) if hasattr(response, "model") else ""
                usage_stats.provider = str(response.provider) if hasattr(response, "provider") else ""
                logger.info(
                    "graph_extractor_llm_call_metrics %s",
                    json.dumps(
                        {
                            "event": "graph_extractor_llm_call_metrics",
                            "chunk_id": chunk_id,
                            **progress_fields,
                            "stage": stage,
                            "latency_ms": latency_ms,
                            "tokens_total": getattr(getattr(response, "usage", None), "total_tokens", 0),
                            "provider": usage_stats.provider,
                            "model": usage_stats.model,
                        },
                        sort_keys=True,
                    ),
                )

                return response

            if track_usage:
                async with collector.track_query(
                    query_id, effective_tenant_id, f"Extract: {chunk_id}"
                ) as qm:
                    qm.operation = "extraction"
                    response = await run_generation(
                        full_text_prompt, llm_config.temperature, stage="extraction_pass_1"
                    )

                    # Update QM with stats
                    qm.tokens_used = usage_stats.total_tokens
                    qm.input_tokens = usage_stats.input_tokens
                    qm.output_tokens = usage_stats.output_tokens
                    qm.cost_estimate = usage_stats.cost_estimate
                    qm.model = usage_stats.model
                    qm.provider = usage_stats.provider

                    # Parse result immediately to log summary
                    parse_result = self.parser.parse(response.text)
                    all_entities.extend(parse_result.entities)
                    all_relationships.extend(parse_result.relationships)

                    # Log friendly summary instead of raw tuple text
                    ent_count = len(parse_result.entities)
                    rel_count = len(parse_result.relationships)
                    qm.response = f"Extracted {ent_count} entities, {rel_count} relationships"
            else:
                # No metrics tracking (aggregated by caller)
                response = await run_generation(
                    full_text_prompt, llm_config.temperature, stage="extraction_pass_1"
                )
                parse_result = self.parser.parse(response.text)
                all_entities.extend(parse_result.entities)
                all_relationships.extend(parse_result.relationships)

        except Exception as e:
            logger.error(f"Extraction pass 1 failed: {e}")
            if track_usage and "qm" in locals():
                qm.response = f"Failed: {str(e)}"

        # 3. Gleaning Pass (Pass 2+)
        should_glean, decision_reason = self._should_run_gleaning(
            runtime_config=runtime_config,
            text=text,
            entity_count=len(all_entities),
            relationship_count=len(all_relationships),
        )

        max_gleaning_steps = min(self.max_gleaning_steps, runtime_config.max_gleaning_steps)
        if should_glean:
            gleaning_run_reason = decision_reason
            for step in range(max_gleaning_steps):
                try:
                    existing_names = [e.name for e in all_entities]
                    if not existing_names:
                        gleaning_skip_reason = "no_entities_after_pass1"
                        break
                    if response is None:
                        gleaning_skip_reason = "missing_pass1_response"
                        break

                    glean_prompt = get_gleaning_prompt(existing_names, self.entity_types)
                    full_glean_prompt = f"{full_text_prompt}\n{response.text}\n\n{glean_prompt}"
                    glean_response = await run_generation(
                        full_glean_prompt,
                        llm_config.temperature,
                        stage=f"gleaning_step_{step + 1}",
                    )
                    gleaning_steps_run += 1

                    glean_result = self.parser.parse(glean_response.text)
                    if not glean_result.entities:
                        gleaning_skip_reason = "no_new_entities"
                        break

                    all_entities.extend(glean_result.entities)
                    all_relationships.extend(glean_result.relationships)

                except Exception as e:
                    gleaning_skip_reason = "gleaning_error"
                    logger.warning(f"Gleaning step {step} failed: {e}")
                    break
        else:
            gleaning_skip_reason = decision_reason

        # 4. Quality Filtering (Intrinsic & QualityScorer)
        final_entities = []
        for ent in all_entities:
            # Intrinsic filter
            if ent.importance_score < 0.5:
                continue

            final_entities.append(ent)

        # Deduplication (Basic implementation) -> Merging same names
        deduped_entities = self._deduplicate_entities(final_entities)
        deduped_relationships = self._deduplicate_relationships(all_relationships)

        # --- POST-EXTRACTION QUALITY FILTER (New) ---
        # If the chunk had low initial quality AND yielded zero entities/relationships,
        # we flag it as noise. This doesn't stop return here, but callers
        # (like the ingestion pipeline) can check for empty results.
        #
        # Note: In a full pipeline, we would return a signal to discard the chunk.
        # Here, returning empty lists is the equivalent of "no knowledge extracted".

        # Check extraction yield
        len(deduped_entities) > 0 or len(deduped_relationships) > 0

        # We don't have access to the raw chunk quality score here easily unless passed in.
        # However, the GraphExtractor's job is just extraction.
        # If we extract nothing, we return nothing.
        # The calling service (IngestionService) should use the chunk's quality_score metadata
        # combined with this empty result to decide whether to index the chunk vector or not.

        # For now, we proceed to return what we found (or didn't find).

        # Convert to Pydantic ExtractionResult for backward compatibility
        # We need to map our semantic Entity model to the Pydantic one expected by callers
        # Note: prompts.entity_extraction.ExtractedEntity matches our schema mostly
        from src.core.generation.application.prompts.entity_extraction import (
            ExtractedEntity,
            ExtractedRelationship,
        )
        from src.core.generation.application.prompts.entity_extraction import (
            ExtractionResult as PydanticResult,
        )

        # Filter relationships to ensure they connect to valid entities
        valid_names = {e.name for e in deduped_entities}

        pydantic_entities = [
            ExtractedEntity(name=e.name, type=e.type, description=e.description)
            for e in deduped_entities
        ]

        pydantic_rels = [
            ExtractedRelationship(
                source=r.source_entity,
                target=r.target_entity,
                type=r.relationship_type,
                description=r.description,
                weight=int(r.strength * 10),
            )
            for r in deduped_relationships
            if r.source_entity in valid_names and r.target_entity in valid_names
        ]

        result = PydanticResult(
            entities=pydantic_entities, relationships=pydantic_rels, usage=usage_stats
        )

        if runtime_config.cache_enabled and cache_key:
            cache = self._get_cache_client(
                redis_url=settings.db.redis_url,
                ttl_seconds=runtime_config.cache_ttl_hours * 3600,
                enabled=True,
            )
            await cache.set(
                cache_key,
                PydanticResult(
                    entities=pydantic_entities,
                    relationships=pydantic_rels,
                    usage=None,
                ),
            )

        logger.info(
            "graph_extractor_chunk_metrics %s",
            json.dumps(
                {
                    "event": "graph_extractor_chunk_metrics",
                    "chunk_id": chunk_id,
                    "tenant_id": effective_tenant_id,
                    **progress_fields,
                    "cache_hit": usage_stats.cache_hit,
                    "gleaning_enabled": self.use_gleaning and runtime_config.use_gleaning,
                    "gleaning_steps_run": gleaning_steps_run,
                    "gleaning_run_reason": gleaning_run_reason,
                    "gleaning_skip_reason": gleaning_skip_reason,
                    "llm_calls": usage_stats.llm_calls,
                    "tokens_total": usage_stats.total_tokens,
                    "entities": len(pydantic_entities),
                    "relationships": len(pydantic_rels),
                },
                sort_keys=True,
            ),
        )

        return result

    def _deduplicate_entities(self, entities: list[Entity]) -> list[Entity]:
        """Simple deduplication by name."""
        unique = {}
        for e in entities:
            key = (e.name.upper(), e.type.upper())
            if key not in unique:
                unique[key] = e
            else:
                # Merge descriptions or scores? For now just keep first (or max score)
                if e.importance_score > unique[key].importance_score:
                    unique[key] = e
        return list(unique.values())

    def _deduplicate_relationships(self, relationships: list[Relationship]) -> list[Relationship]:
        """Deduplicate relationships by source-target-type."""
        unique = {}
        for r in relationships:
            # Key: Source -> Target (Type)
            key = (r.source_entity.upper(), r.target_entity.upper(), r.relationship_type.upper())
            if key not in unique:
                unique[key] = r
            else:
                # Keep higher strength
                if r.strength > unique[key].strength:
                    unique[key] = r
        return list(unique.values())
