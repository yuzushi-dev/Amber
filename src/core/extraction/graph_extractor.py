import logging
import json
from typing import List, Optional
from pydantic import ValidationError

from src.core.providers.factory import get_llm_provider
from src.core.providers.base import ProviderTier
from src.core.prompts.entity_extraction import (
    EXTRACTION_SYSTEM_PROMPT, 
    GLEANING_SYSTEM_PROMPT, 
    ExtractionResult
)

logger = logging.getLogger(__name__)

class GraphExtractor:
    """
    Service to extract Knowledge Graph elements (Entities, Relationships) from text.
    Uses 'Gleaning' (Iterative Extraction) to maximize recall.
    """
    
    def __init__(self, use_gleaning: bool = True, max_gleaning_steps: int = 1):
        self.use_gleaning = use_gleaning
        self.max_gleaning_steps = max_gleaning_steps

    async def extract(self, text: str) -> ExtractionResult:
        """
        Extract entities and relationships from the text.
        
        Args:
            text: Input text chunk.
            
        Returns:
            ExtractionResult containing list of entities and relationships.
        """
        # Enforce Economy Tier for cost savings as per user requirement
        provider = get_llm_provider(tier=ProviderTier.ECONOMY)
        
        # 1. Initial Extraction
        try:
             result_json = await provider.generate(
                 prompt=f"Text to extract from:\n\n{text}",
                 system_prompt=EXTRACTION_SYSTEM_PROMPT,
                 temperature=0.0 # Deterministic
             )
             base_result = self._parse_result(result_json.text)
        except Exception as e:
             logger.error(f"Initial extraction failed: {e}")
             return ExtractionResult()

        if not self.use_gleaning:
            return base_result
            
        # 2. Gleaning Loop
        current_result = base_result
        for i in range(self.max_gleaning_steps):
            try:
                # Construct list of existing entities for context to avoid duplicates
                existing_names = [e.name for e in current_result.entities]
                prompt = f"Text:\n{text}\n\nExisting Entities: {', '.join(existing_names)}"
                
                glean_output = await provider.generate(
                    prompt=prompt,
                    system_prompt=GLEANING_SYSTEM_PROMPT,
                    temperature=0.2 # Slightly higher for creativity in finding missed items
                )
                
                new_items = self._parse_result(glean_output.text)
                
                # If no new entities, stop gleaning
                if not new_items.entities:
                    break
                    
                # Merge results
                # In a real implementation we might want to dedupe here, but we'll trust the LLM 
                # respects the "Existing Entities" list for now, and handle dedupe at DB write time.
                current_result.entities.extend(new_items.entities)
                current_result.relationships.extend(new_items.relationships)
                
            except Exception as e:
                logger.warning(f"Gleaning step {i+1} failed: {e}")
                break
                
        return current_result

    def _parse_result(self, json_text: str) -> ExtractionResult:
        """Parse JSON response into Pydantic model."""
        # Clean markdown code blocks if present
        cleaned_text = json_text.strip()
        if cleaned_text.startswith("```json"):
            cleaned_text = cleaned_text[7:]
        if cleaned_text.startswith("```"):
            cleaned_text = cleaned_text[3:]
        if cleaned_text.endswith("```"):
            cleaned_text = cleaned_text[:-3]
        cleaned_text = cleaned_text.strip()

        try:
            # Parse JSON first
            data = json.loads(cleaned_text)
            return ExtractionResult(**data)
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON generated: {json_text[:100]}...")
            return ExtractionResult()
        except ValidationError as e:
             logger.error(f"Validation Error: {e}")
             return ExtractionResult()
