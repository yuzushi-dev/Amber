from enum import Enum


class NodeLabel(str, Enum):
    Document = "Document"
    Chunk = "Chunk"
    Entity = "Entity"
    Community = "Community"

class RelationshipType(str, Enum):
    HAS_CHUNK = "HAS_CHUNK"
    MENTIONS = "MENTIONS"
    RELATED_TO = "RELATED_TO"
    SIMILAR_TO = "SIMILAR_TO"
    IN_COMMUNITY = "IN_COMMUNITY"
    POTENTIALLY_SAME_AS = "POTENTIALLY_SAME_AS"
    SAME_AS = "SAME_AS"
