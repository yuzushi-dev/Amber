
from pydantic import BaseModel, Field


class ExtractedEntity(BaseModel):
    name: str = Field(..., description="Name of the entity. Capitalize properly.")
    type: str = Field(..., description="Type of the entity (e.g., PERSON, ORGANIZATION, LOCATION, EVENT, CONCEPT, PRODUCT, DOCUMENT).")
    description: str = Field(..., description="Brief, comprehensive description of the entity based on the text.")

class ExtractedRelationship(BaseModel):
    source: str = Field(..., description="Name of the source entity (must match an extracted entity name).")
    target: str = Field(..., description="Name of the target entity (must match an extracted entity name).")
    type: str = Field(..., description="Type of the relationship (UPPER_SNAKE_CASE, e.g., AUTHORED, DEPLOYED_ON, HAS_IMPACT).")
    description: str = Field(..., description="Description of how the source is related to the target.")
    weight: float = Field(default=1.0, description="Strength of the relationship (0.0-1.0) based on importance/frequency.")

class ExtractionUsage(BaseModel):
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_estimate: float = 0.0
    model: str = ""
    provider: str = ""

class ExtractionResult(BaseModel):
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relationships: list[ExtractedRelationship] = Field(default_factory=list)
    usage: ExtractionUsage | None = None


# Dynamic Tuple-based Prompt Generation

def get_tuple_extraction_prompt(entity_types: list[str], relation_types: list[str], text_unit_id: str = "UNKNOWN") -> str:
    """Generate prompt for tuple-delimited format (Phase 3)."""
    entity_types_str = ", ".join(entity_types)
    relation_types_str = ", ".join(relation_types)

    return f"""FORMAT: TUPLE_V1

You are an expert at extracting entities and relationships from text.

You are processing TextUnit ID: {text_unit_id}. Always preserve this identifier for provenance.

**Task**: Extract all relevant entities and relationships in tuple-delimited format.

**Entity Types (ontology)**: Use only these canonical types: {entity_types_str}
**Relationship Types**: Prefer these relationship patterns when applicable: {relation_types_str}

**CRITICAL OUTPUT FORMAT RULES**:
1. Use TUPLE-DELIMITED format with <|> as field separator
2. Entity format: ("entity"<|>NAME<|>TYPE<|>DESCRIPTION<|>IMPORTANCE)
3. Relationship format: ("relationship"<|>SOURCE<|>TARGET<|>TYPE<|>DESCRIPTION<|>STRENGTH)
4. UPPERCASE all entity names and types
5. NEVER use <|> inside descriptions (use | or - instead)
6. One tuple per line
7. Importance and Strength must be 0.0-1.0
8. Empty descriptions allowed but name and type are REQUIRED

**EXAMPLES**:
("entity"<|>ADMIN PANEL<|>COMPONENT<|>Web-based administration interface<|>0.9)
("entity"<|>USER DATABASE<|>SERVICE<|>Database storing user authentication data<|>0.8)
("entity"<|>LOGIN SERVICE<|>SERVICE<|>Handles user authentication<|>0.85)
("relationship"<|>ADMIN PANEL<|>USER DATABASE<|>DEPENDS_ON<|>Admin panel queries database for authentication<|>0.7)
("relationship"<|>LOGIN SERVICE<|>USER DATABASE<|>QUERIES<|>Login service reads user credentials from database<|>0.8)

**Instructions**:
1. Extract ALL relevant entities from the text
2. Use exact entity names from the text (converted to UPPERCASE)
3. Choose types from the canonical list above
4. Provide concise, factual descriptions grounded in the text
5. Rate importance (entities) and strength (relationships) based on context
6. AVOID using <|> delimiter in descriptions
"""

def get_gleaning_prompt(existing_entities: list[str], entity_types: list[str]) -> str:
    """Generate continuation prompt for gleaning pass."""
    # Show sample of already-extracted entities
    entity_sample = existing_entities[:20] # Show up to 20
    summary = ", ".join(entity_sample)
    if len(existing_entities) > 20:
        summary += f" (and {len(existing_entities) - 20} more)"

    entity_types_str = ", ".join(entity_types)

    return f"""**Already extracted entities:** {summary}

IMPORTANT: MANY additional entities and relationships were MISSED in the previous extraction pass.

**Your task:**
- Identify ADDITIONAL entities and relationships you overlooked
- Use ONLY the canonical entity types: {entity_types_str}
- Use the SAME output format ("entity"<|>...)
- Extract ONLY NEW entities (do NOT repeat entities already extracted)
- Be thorough and careful

**Additional entities and relationships:**"""

