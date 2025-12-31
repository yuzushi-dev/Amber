from pydantic import BaseModel, Field
from typing import List

class ExtractedEntity(BaseModel):
    name: str = Field(..., description="Name of the entity. Capitalize properly.")
    type: str = Field(..., description="Type of the entity (e.g., PERSON, ORGANIZATION, LOCATION, EVENT, CONCEPT, PRODUCT, DOCUMENT).")
    description: str = Field(..., description="Brief, comprehensive description of the entity based on the text.")

class ExtractedRelationship(BaseModel):
    source: str = Field(..., description="Name of the source entity (must match an extracted entity name).")
    target: str = Field(..., description="Name of the target entity (must match an extracted entity name).")
    type: str = Field(..., description="Type of the relationship (UPPER_SNAKE_CASE, e.g., AUTHORED, DEPLOYED_ON, HAS_IMPACT).")
    description: str = Field(..., description="Description of how the source is related to the target.")
    weight: int = Field(default=1, description="Strength of the relationship (1-10) based on importance/frequency.")

class ExtractionResult(BaseModel):
    entities: List[ExtractedEntity] = Field(default_factory=list)
    relationships: List[ExtractedRelationship] = Field(default_factory=list)

# System Prompt for Graph Extraction
EXTRACTION_SYSTEM_PROMPT = """
You are an expert Knowledge Graph builder. Your task is to extract structured entities and relationships from the provided text.

GUIDELINES:
1. Identify key entities (People, Organizations, Locations, Concepts, Events, Products).
2. Extract meaningful relationships between them.
3. Use consistent naming (e.g., "Microsoft" instead of "Microsoft Corp." if referred to as such).
4. Relationships should have descriptive types (e.g., 'ACQUIRED', 'LOCATED_IN') and context in the description.
5. Entity descriptions should be self-contained summaries of what the text says about the entity.
6. AVOID generic entities like "User", "The System", "It", "They" unless they are specific named concepts.

OUTPUT FORMAT:
Return a JSON object matching the schema:
{
  "entities": [{"name": "...", "type": "...", "description": "..."}],
  "relationships": [{"source": "...", "target": "...", "type": "...", "description": "...", "weight": 1}]
}
"""

GLEANING_SYSTEM_PROMPT = """
You are an expert Knowledge Graph builder. You are performing a "Gleaning" pass to catch any entities or relationships missed in the first extraction.
Review the text again and the LIST OF ALREADY EXTRACTED ENTITIES provided.
Extract ONLY NEW entities and relationships that are NOT in the provided list but are important.
If no new significant entities are found, return empty lists.
"""
