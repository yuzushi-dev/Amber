"""
Identifier Generation and Validation
=====================================

Type-safe identifiers for documents, chunks, entities, and tenants.
All identifiers use prefixed UUIDs for clear type identification.
"""

import re
import uuid
from typing import NewType

# =============================================================================
# Type Definitions
# =============================================================================

DocumentId = NewType("DocumentId", str)
ChunkId = NewType("ChunkId", str)
EntityId = NewType("EntityId", str)
TenantId = NewType("TenantId", str)
RequestId = NewType("RequestId", str)
ConversationId = NewType("ConversationId", str)

# =============================================================================
# Identifier Patterns
# =============================================================================

# Pattern: prefix_16hexchars (e.g., doc_a1b2c3d4e5f6g7h8)
DOCUMENT_ID_PATTERN = re.compile(r"^doc_[a-f0-9]{16}$")
CHUNK_ID_PATTERN = re.compile(r"^chunk_[a-f0-9]{16}_\d{5}$")
ENTITY_ID_PATTERN = re.compile(r"^ent_[a-f0-9]{16}$")
TENANT_ID_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{2,31}$")
REQUEST_ID_PATTERN = re.compile(r"^req_[a-f0-9]{32}$")
CONVERSATION_ID_PATTERN = re.compile(r"^conv_[a-f0-9]{16}$")


# =============================================================================
# Generation Functions
# =============================================================================


def generate_document_id() -> DocumentId:
    """
    Generate a unique document identifier.

    Format: doc_<16 hex chars>
    Example: doc_a1b2c3d4e5f67890

    Returns:
        DocumentId: Unique document identifier
    """
    return DocumentId(f"doc_{uuid.uuid4().hex[:16]}")


def generate_chunk_id(document_id: DocumentId | str, index: int) -> ChunkId:
    """
    Generate a chunk identifier tied to its parent document.

    Format: chunk_<doc_hex>_<5-digit index>
    Example: chunk_a1b2c3d4e5f67890_00001

    Args:
        document_id: Parent document identifier
        index: Zero-based chunk index within the document

    Returns:
        ChunkId: Unique chunk identifier
    """
    # Extract the hex portion from the document ID
    if isinstance(document_id, str) and document_id.startswith("doc_"):
        doc_hex = document_id[4:]
    else:
        doc_hex = str(document_id)[:16]

    return ChunkId(f"chunk_{doc_hex}_{index:05d}")


def generate_entity_id() -> EntityId:
    """
    Generate a unique entity identifier.

    Format: ent_<16 hex chars>
    Example: ent_a1b2c3d4e5f67890

    Returns:
        EntityId: Unique entity identifier
    """
    return EntityId(f"ent_{uuid.uuid4().hex[:16]}")


def generate_request_id() -> RequestId:
    """
    Generate a unique request identifier.

    Format: req_<32 hex chars>
    Example: req_a1b2c3d4e5f67890a1b2c3d4e5f67890

    Returns:
        RequestId: Unique request identifier
    """
    return RequestId(f"req_{uuid.uuid4().hex}")


def generate_conversation_id() -> ConversationId:
    """
    Generate a unique conversation identifier.

    Format: conv_<16 hex chars>
    Example: conv_a1b2c3d4e5f67890

    Returns:
        ConversationId: Unique conversation identifier
    """
    return ConversationId(f"conv_{uuid.uuid4().hex[:16]}")


# Type for query identifiers
QueryId = NewType("QueryId", str)
QUERY_ID_PATTERN = re.compile(r"^qry_[a-f0-9]{16}$")


def generate_query_id() -> QueryId:
    """
    Generate a unique query identifier.

    Format: qry_<16 hex chars>
    Example: qry_a1b2c3d4e5f67890

    Returns:
        QueryId: Unique query identifier
    """
    return QueryId(f"qry_{uuid.uuid4().hex[:16]}")


# Type for community identifiers
CommunityId = NewType("CommunityId", str)
COMMUNITY_ID_PATTERN = re.compile(r"^comm_\d+_[a-f0-9]{8}$")


def generate_community_id(level: int = 0) -> CommunityId:
    """
    Generate a unique community identifier.

    Format: comm_<level>_<8 hex chars>
    Example: comm_0_a1b2c3d4

    Args:
        level: Community hierarchy level (0=base)

    Returns:
        CommunityId: Unique community identifier
    """
    return CommunityId(f"comm_{level}_{uuid.uuid4().hex[:8]}")


# =============================================================================
# Validation Functions
# =============================================================================


def validate_document_id(id_str: str) -> bool:
    """
    Validate a document identifier format.

    Args:
        id_str: String to validate

    Returns:
        bool: True if valid document ID format
    """
    return bool(DOCUMENT_ID_PATTERN.match(id_str))


def validate_chunk_id(id_str: str) -> bool:
    """
    Validate a chunk identifier format.

    Args:
        id_str: String to validate

    Returns:
        bool: True if valid chunk ID format
    """
    return bool(CHUNK_ID_PATTERN.match(id_str))


def validate_entity_id(id_str: str) -> bool:
    """
    Validate an entity identifier format.

    Args:
        id_str: String to validate

    Returns:
        bool: True if valid entity ID format
    """
    return bool(ENTITY_ID_PATTERN.match(id_str))


def validate_tenant_id(id_str: str) -> bool:
    """
    Validate a tenant identifier format.

    Tenant IDs must:
    - Start with a letter
    - Be 3-32 characters long
    - Contain only letters, numbers, underscores, and hyphens

    Args:
        id_str: String to validate

    Returns:
        bool: True if valid tenant ID format
    """
    return bool(TENANT_ID_PATTERN.match(id_str))


def validate_request_id(id_str: str) -> bool:
    """
    Validate a request identifier format.

    Also accepts standard UUIDs for client-provided request IDs.

    Args:
        id_str: String to validate

    Returns:
        bool: True if valid request ID format
    """
    if REQUEST_ID_PATTERN.match(id_str):
        return True
    # Also accept standard UUIDs
    try:
        uuid.UUID(id_str)
        return True
    except ValueError:
        return False


def validate_community_id(id_str: str) -> bool:
    """
    Validate a community identifier format.

    Args:
        id_str: String to validate

    Returns:
        bool: True if valid community ID format
    """
    return bool(COMMUNITY_ID_PATTERN.match(id_str))


# =============================================================================
# Extraction Functions
# =============================================================================


def extract_document_id_from_chunk(chunk_id: ChunkId | str) -> DocumentId | None:
    """
    Extract the parent document ID from a chunk ID.

    Args:
        chunk_id: Chunk identifier

    Returns:
        DocumentId or None if chunk_id is invalid
    """
    if isinstance(chunk_id, str) and chunk_id.startswith("chunk_"):
        parts = chunk_id.split("_")
        if len(parts) >= 2:
            return DocumentId(f"doc_{parts[1]}")
    return None
