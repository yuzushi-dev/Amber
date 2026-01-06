"""
Tuple-based parser for robust entity extraction.
Parses pipe-delimited output format (Phase 3) into Entity and Relationship objects.
"""

import logging
from dataclasses import dataclass

from src.core.models.kg import Entity, Relationship

logger = logging.getLogger(__name__)


@dataclass
class ParseResult:
    """Result of parsing operations."""
    entities: list[Entity]
    relationships: list[Relationship]
    parse_errors: list[str]
    valid_count: int
    invalid_count: int


class TupleParser:
    """Parses tuple-delimited LLM output for KG extraction."""

    def __init__(self, chunk_id: str | None = None):
        self.chunk_id = chunk_id
        self._stats = {"total_lines": 0, "entities": 0, "relationships": 0, "parse_errors": 0}

    def parse(self, text: str) -> ParseResult:
        """
        Parse raw text containing tuple-delimited entities and relationships.

        Format:
        ("entity"<|>NAME<|>TYPE<|>DESCRIPTION<|>IMPORTANCE)
        ("relationship"<|>SOURCE<|>TARGET<|>TYPE<|>DESCRIPTION<|>STRENGTH)
        """
        entities: list[Entity] = []
        relationships: list[Relationship] = []
        parse_errors: list[str] = []

        # Split into lines and filter empty ones
        lines = [line.strip() for line in text.strip().split('\n') if line.strip()]
        self._stats["total_lines"] = len(lines)

        for line_num, line in enumerate(lines, 1):
            try:
                # Basic validation
                parsed = self._parse_tuple_line(line)
                if not parsed:
                    err = f"Line {line_num}: Invalid tuple format - {line[:50]}..."
                    # Only log strictly invalid lines if they look like they attempted to be tuples
                    if line.startswith("(") or "<|>" in line:
                         parse_errors.append(err)
                         self._stats["parse_errors"] += 1
                         logger.debug(err)
                    continue

                tuple_type, fields = parsed

                if tuple_type == "entity":
                    entity = self._parse_entity_tuple(fields, line_num)
                    if entity:
                        entities.append(entity)
                        self._stats["entities"] += 1
                    else:
                        parse_errors.append(f"Line {line_num}: Failed to parse entity tuple")
                        self._stats["parse_errors"] += 1

                elif tuple_type == "relationship":
                    relationship = self._parse_relationship_tuple(fields, line_num)
                    if relationship:
                        relationships.append(relationship)
                        self._stats["relationships"] += 1
                    else:
                        parse_errors.append(f"Line {line_num}: Failed to parse relationship tuple")
                        self._stats["parse_errors"] += 1

                else:
                    logger.debug(f"Line {line_num}: Unknown tuple type '{tuple_type}'")
                    parse_errors.append(f"Line {line_num}: Unknown tuple type '{tuple_type}'")
                    self._stats["parse_errors"] += 1

            except Exception as e:
                logger.warning(f"Line {line_num}: Parse error - {str(e)}")
                parse_errors.append(f"Line {line_num}: {str(e)}")
                self._stats["parse_errors"] += 1
                continue

        valid_count = len(entities) + len(relationships)
        invalid_count = len(parse_errors)

        logger.info(
            f"Tuple parsing complete: {len(entities)} entities, "
            f"{len(relationships)} relationships, {invalid_count} errors"
        )

        return ParseResult(
            entities=entities,
            relationships=relationships,
            parse_errors=parse_errors,
            valid_count=valid_count,
            invalid_count=invalid_count
        )

    def _parse_tuple_line(self, line: str) -> tuple[str, list[str]] | None:
        """
        Parse a single tuple line.

        Returns:
            (tuple_type, fields) or None if not a valid tuple
        """
        # Check if line looks like a tuple
        if not (line.startswith('("') and line.endswith(')')):
            return None

        # Remove outer parentheses
        inner = line[1:-1]  # Remove leading ( and trailing )

        # Check for opening quote
        if not inner.startswith('"'):
            return None

        # Find closing quote for type field
        type_end = inner.find('"', 1)
        if type_end == -1:
            return None

        # Extract type
        tuple_type = inner[1:type_end].strip().lower()

        # Get remaining content after type
        remaining = inner[type_end + 1:]

        # Check for delimiter after type
        if not remaining.startswith('<|>'):
            return None

        # Remove leading delimiter
        remaining = remaining[3:]  # Remove <|>

        # Split by delimiter to get fields
        fields = remaining.split('<|>')

        # Trim whitespace from all fields
        fields = [f.strip() for f in fields]

        return (tuple_type, fields)

    def _parse_entity_tuple(self, fields: list[str], line_num: int) -> Entity | None:
        """Parse entity tuple fields into Entity object."""
        if len(fields) < 2:
            logger.warning(
                f"Line {line_num}: Entity tuple has insufficient fields "
                f"(expected 3-4, got {len(fields)})"
            )
            return None

        # Extract fields
        name = fields[0].strip()
        entity_type = fields[1].strip() if len(fields) > 1 else ""
        description = fields[2].strip() if len(fields) > 2 else ""
        importance = float(fields[3]) if len(fields) > 3 and fields[3].strip() else 0.5

        # Validate name (required)
        if not name:
            logger.warning(f"Line {line_num}: Entity tuple has empty name")
            return None

        # Normalize type (uppercase)
        entity_type = entity_type.upper()

        # Validate importance range
        if importance < 0.0 or importance > 1.0:
            logger.warning(
                f"Line {line_num}: Invalid importance {importance}, using 0.5"
            )
            importance = 0.5

        # Create Entity object
        entity = Entity(
            name=name,
            type=entity_type,
            description=description,
            importance_score=importance,
            source_text_units=[self.chunk_id] if self.chunk_id else [],
            source_chunks=[self.chunk_id] if self.chunk_id else [],
        )

        return entity

    def _parse_relationship_tuple(
        self,
        fields: list[str],
        line_num: int
    ) -> Relationship | None:
        """Parse relationship tuple fields into Relationship object."""
        if len(fields) < 3:
            logger.warning(
                f"Line {line_num}: Relationship tuple has insufficient fields "
                f"(expected 4-5, got {len(fields)})"
            )
            return None

        # Extract fields
        source = fields[0].strip()
        target = fields[1].strip()
        rel_type = fields[2].strip()
        description = fields[3].strip() if len(fields) > 3 else ""
        strength = float(fields[4]) if len(fields) > 4 and fields[4].strip() else 0.5

        # Validate required fields
        if not source or not target:
            logger.warning(
                f"Line {line_num}: Relationship tuple has empty source or target"
            )
            return None

        # Normalize relationship type (uppercase, underscores)
        rel_type = rel_type.upper().replace(' ', '_')

        # Validate strength range
        if strength < 0.0 or strength > 1.0:
            logger.warning(
                f"Line {line_num}: Invalid strength {strength}, using 0.5"
            )
            strength = 0.5

        # Create Relationship object
        relationship = Relationship(
            source_entity=source,
            target_entity=target,
            relationship_type=rel_type,
            description=description,
            strength=strength,
            source_text_units=[self.chunk_id] if self.chunk_id else [],
            source_chunks=[self.chunk_id] if self.chunk_id else [],
        )

        return relationship
