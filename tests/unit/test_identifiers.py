"""
Unit Tests for Identifier Generation and Validation
====================================================
"""

import pytest

from src.shared.identifiers import (
    ChunkId,
    DocumentId,
    EntityId,
    extract_document_id_from_chunk,
    generate_chunk_id,
    generate_community_id,
    generate_conversation_id,
    generate_document_id,
    generate_entity_id,
    generate_request_id,
    validate_chunk_id,
    validate_community_id,
    validate_document_id,
    validate_entity_id,
    validate_request_id,
    validate_tenant_id,
)


class TestDocumentId:
    """Tests for document ID generation and validation."""

    def test_generate_document_id_format(self):
        """Generated document IDs should have correct format."""
        doc_id = generate_document_id()
        assert doc_id.startswith("doc_")
        assert len(doc_id) == 20  # doc_ + 16 hex chars

    def test_generate_document_id_unique(self):
        """Generated document IDs should be unique."""
        ids = {generate_document_id() for _ in range(100)}
        assert len(ids) == 100

    def test_validate_document_id_valid(self):
        """Valid document IDs should pass validation."""
        assert validate_document_id("doc_a1b2c3d4e5f67890")
        assert validate_document_id("doc_0000000000000000")
        assert validate_document_id("doc_ffffffffffffffff")

    def test_validate_document_id_invalid(self):
        """Invalid document IDs should fail validation."""
        assert not validate_document_id("")
        assert not validate_document_id("doc_")
        assert not validate_document_id("document_abc123")
        assert not validate_document_id("doc_abc")  # Too short
        assert not validate_document_id("doc_abc123def456789xyz")  # Too long
        assert not validate_document_id("doc_ABCDEFGHIJKLMNOP")  # Uppercase


class TestChunkId:
    """Tests for chunk ID generation and validation."""

    def test_generate_chunk_id_format(self):
        """Generated chunk IDs should have correct format."""
        doc_id = DocumentId("doc_a1b2c3d4e5f67890")
        chunk_id = generate_chunk_id(doc_id, 0)
        assert chunk_id.startswith("chunk_")
        assert "_00000" in chunk_id

    def test_generate_chunk_id_includes_doc_id(self):
        """Chunk IDs should include parent document ID."""
        doc_id = DocumentId("doc_a1b2c3d4e5f67890")
        chunk_id = generate_chunk_id(doc_id, 5)
        assert "a1b2c3d4e5f67890" in chunk_id
        assert chunk_id.endswith("_00005")

    def test_generate_chunk_id_index_padding(self):
        """Chunk index should be zero-padded to 5 digits."""
        doc_id = DocumentId("doc_a1b2c3d4e5f67890")
        assert generate_chunk_id(doc_id, 0).endswith("_00000")
        assert generate_chunk_id(doc_id, 99).endswith("_00099")
        assert generate_chunk_id(doc_id, 12345).endswith("_12345")

    def test_validate_chunk_id_valid(self):
        """Valid chunk IDs should pass validation."""
        assert validate_chunk_id("chunk_a1b2c3d4e5f67890_00001")
        assert validate_chunk_id("chunk_0000000000000000_99999")

    def test_validate_chunk_id_invalid(self):
        """Invalid chunk IDs should fail validation."""
        assert not validate_chunk_id("")
        assert not validate_chunk_id("chunk_abc_001")  # Wrong format
        assert not validate_chunk_id("doc_abc123")  # Wrong prefix


class TestEntityId:
    """Tests for entity ID generation and validation."""

    def test_generate_entity_id_format(self):
        """Generated entity IDs should have correct format."""
        entity_id = generate_entity_id()
        assert entity_id.startswith("ent_")
        assert len(entity_id) == 20  # ent_ + 16 hex chars

    def test_generate_entity_id_unique(self):
        """Generated entity IDs should be unique."""
        ids = {generate_entity_id() for _ in range(100)}
        assert len(ids) == 100

    def test_validate_entity_id_valid(self):
        """Valid entity IDs should pass validation."""
        assert validate_entity_id("ent_a1b2c3d4e5f67890")

    def test_validate_entity_id_invalid(self):
        """Invalid entity IDs should fail validation."""
        assert not validate_entity_id("entity_abc123")
        assert not validate_entity_id("ent_abc")


class TestCommunityId:
    """Tests for community ID generation and validation."""

    def test_generate_community_id_format(self):
        """Generated community IDs should have correct format."""
        comm_id = generate_community_id(level=0)
        assert comm_id.startswith("comm_0_")
        assert len(comm_id) >= 15  # comm_0_ + 8 hex chars

        comm_id_l1 = generate_community_id(level=1)
        assert comm_id_l1.startswith("comm_1_")

    def test_validate_community_id_valid(self):
        """Valid community IDs should pass validation."""
        assert validate_community_id("comm_0_a1b2c3d4")
        assert validate_community_id("comm_10_ffffffff")

    def test_validate_community_id_invalid(self):
        """Invalid community IDs should fail validation."""
        assert not validate_community_id("comm_a1b2c3d4")  # Missing level
        assert not validate_community_id("comm_x_a1b2c3d4")  # Invalid level
        assert not validate_community_id("comm_0_a1b2c3d4e5")  # Too long hex


class TestTenantId:
    """Tests for tenant ID validation."""

    def test_validate_tenant_id_valid(self):
        """Valid tenant IDs should pass validation."""
        assert validate_tenant_id("default")
        assert validate_tenant_id("tenant_001")
        assert validate_tenant_id("my-tenant")
        assert validate_tenant_id("MyTenant123")

    def test_validate_tenant_id_invalid(self):
        """Invalid tenant IDs should fail validation."""
        assert not validate_tenant_id("")
        assert not validate_tenant_id("ab")  # Too short
        assert not validate_tenant_id("1tenant")  # Starts with number
        assert not validate_tenant_id("tenant@domain")  # Invalid char
        assert not validate_tenant_id("a" * 50)  # Too long


class TestRequestId:
    """Tests for request ID generation and validation."""

    def test_generate_request_id_format(self):
        """Generated request IDs should have correct format."""
        request_id = generate_request_id()
        assert request_id.startswith("req_")
        assert len(request_id) == 36  # req_ + 32 hex chars

    def test_validate_request_id_valid(self):
        """Valid request IDs should pass validation."""
        assert validate_request_id("req_a1b2c3d4e5f67890a1b2c3d4e5f67890")
        # Also accepts UUIDs
        assert validate_request_id("550e8400-e29b-41d4-a716-446655440000")

    def test_validate_request_id_invalid(self):
        """Invalid request IDs should fail validation."""
        assert not validate_request_id("")
        assert not validate_request_id("request_abc")
        assert not validate_request_id("not-a-uuid")


class TestExtractDocumentId:
    """Tests for extracting document ID from chunk ID."""

    def test_extract_document_id_valid(self):
        """Should extract document ID from valid chunk ID."""
        chunk_id = ChunkId("chunk_a1b2c3d4e5f67890_00001")
        doc_id = extract_document_id_from_chunk(chunk_id)
        assert doc_id == "doc_a1b2c3d4e5f67890"

    def test_extract_document_id_invalid(self):
        """Should return None for invalid chunk IDs."""
        assert extract_document_id_from_chunk("invalid") is None
        assert extract_document_id_from_chunk("doc_abc123") is None
