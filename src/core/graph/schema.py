from enum import Enum


class NodeLabel(str, Enum):
    # Knowledge Graph nodes
    Document = "Document"
    Chunk = "Chunk"
    Entity = "Entity"
    Community = "Community"
    
    # Context Graph nodes (Decision Traces)
    Conversation = "Conversation"
    Turn = "Turn"
    UserFeedback = "UserFeedback"


class RelationshipType(str, Enum):
    # Knowledge Graph relationships
    HAS_CHUNK = "HAS_CHUNK"
    MENTIONS = "MENTIONS"
    RELATED_TO = "RELATED_TO"
    SIMILAR_TO = "SIMILAR_TO"
    IN_COMMUNITY = "IN_COMMUNITY"
    POTENTIALLY_SAME_AS = "POTENTIALLY_SAME_AS"
    SAME_AS = "SAME_AS"
    
    # Context Graph relationships
    HAS_TURN = "HAS_TURN"           # Conversation -> Turn
    NEXT_TURN = "NEXT_TURN"         # Turn -> Turn (conversation threading)
    RETRIEVED = "RETRIEVED"         # Turn -> Chunk (decision trace: which chunks were used)
    RATES = "RATES"                 # UserFeedback -> Turn

