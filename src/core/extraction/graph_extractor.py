import json
import logging
from pathlib import Path

from src.core.extraction.tuple_parser import TupleParser
from src.core.models.kg import Entity, Relationship
from src.core.prompts.entity_extraction import (
    ExtractionResult,  # We keep this for external compat types if needed
    get_gleaning_prompt,
    get_tuple_extraction_prompt,
)
from src.core.providers.base import ProviderTier
from src.core.providers.factory import get_llm_provider

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
                    data.get("relationship_suggestions", ["RELATED_TO"])
                )
        except Exception as e:
            logger.error(f"Failed to load classification config: {e}")
            return (["CONCEPT"], ["RELATED_TO"])

    async def extract(self, text: str, chunk_id: str = "UNKNOWN") -> ExtractionResult:
        """
        Extract entities/relationships using tuple format + quality scoring.
        """
        # 1. Prepare Provider
        provider = get_llm_provider(tier=ProviderTier.ECONOMY)

        # 2. Initial Pass (Pass 1)
        # We use a standard prompt instead of system_prompt for tuple format to avoid strict JSON mode constraints on some providers
        initial_prompt = get_tuple_extraction_prompt(
            self.entity_types,
            self.relationship_suggestions,
            text_unit_id=chunk_id
        )

        full_text_prompt = f"{initial_prompt}\n\n**Text to analyze**:\n{text}\n\n**Output (tuple format only)**:"

        all_entities: list[Entity] = []
        all_relationships: list[Relationship] = []

        # Metrics tracking for extraction
        from src.api.config import settings
        from src.core.metrics.collector import MetricsCollector
        from src.shared.identifiers import generate_query_id
        
        query_id = generate_query_id()
        collector = MetricsCollector(redis_url=settings.db.redis_url)

        try:
            async with collector.track_query(query_id, "system", f"Extract: {chunk_id}") as qm:
                qm.operation = "extraction"
                response = await provider.generate(
                    prompt=full_text_prompt,
                    temperature=0.1 # Low temp for stability
                )
                qm.tokens_used = response.usage.total_tokens if hasattr(response, 'usage') else 0
                qm.input_tokens = response.usage.input_tokens if hasattr(response, 'usage') else 0
                qm.output_tokens = response.usage.output_tokens if hasattr(response, 'usage') else 0
                qm.cost_estimate = response.cost_estimate if hasattr(response, 'cost_estimate') else 0.0
                qm.model = response.model if hasattr(response, 'model') else ""
                qm.provider = response.provider if hasattr(response, 'provider') else ""
                qm.response = response.text[:500] if len(response.text) > 500 else response.text

            # Parse result
            parse_result = self.parser.parse(response.text)
            all_entities.extend(parse_result.entities)
            all_relationships.extend(parse_result.relationships)

        except Exception as e:
            logger.error(f"Extraction pass 1 failed: {e}")

        # 3. Gleaning Pass (Pass 2+)
        if self.use_gleaning and self.max_gleaning_steps > 0:
            for step in range(self.max_gleaning_steps):
                try:
                    existing_names = [e.name for e in all_entities]
                    if not existing_names:
                        break # Nothing found, maybe empty text?

                    glean_prompt = get_gleaning_prompt(existing_names, self.entity_types)
                    full_glean_prompt = f"{full_text_prompt}\n{response.text}\n\n{glean_prompt}"

                    glean_response = await provider.generate(
                        prompt=full_glean_prompt,
                        temperature=0.3 # Slightly higher for recall
                    )

                    glean_result = self.parser.parse(glean_response.text)
                    if not glean_result.entities:
                        break # Stop if no new entities found

                    all_entities.extend(glean_result.entities)
                    all_relationships.extend(glean_result.relationships)

                except Exception as e:
                    logger.warning(f"Gleaning step {step} failed: {e}")
                    break

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
        from src.core.prompts.entity_extraction import ExtractedEntity, ExtractedRelationship
        from src.core.prompts.entity_extraction import ExtractionResult as PydanticResult

        # Filter relationships to ensure they connect to valid entities
        valid_names = {e.name for e in deduped_entities}

        pydantic_entities = [
            ExtractedEntity(
                name=e.name,
                type=e.type,
                description=e.description
            ) for e in deduped_entities
        ]

        pydantic_rels = [
            ExtractedRelationship(
                source=r.source_entity,
                target=r.target_entity,
                type=r.relationship_type,
                description=r.description,
                weight=int(r.strength * 10)
            ) for r in deduped_relationships if r.source_entity in valid_names and r.target_entity in valid_names
        ]

        return PydanticResult(entities=pydantic_entities, relationships=pydantic_rels)

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


