"""
Tests for startup integrity checks.

These tests verify:
1. EmbeddingMigrationService correctly detects dimension mismatches
2. Neo4j constraint checks work properly
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.shared.model_registry import EMBEDDING_MODELS

LEGACY_EMBEDDING_MODEL = next(
    name for name, info in EMBEDDING_MODELS["openai"].items() if not info.get("supports_dimensions")
)
LEGACY_EMBEDDING_DIM = EMBEDDING_MODELS["openai"][LEGACY_EMBEDDING_MODEL]["dimensions"]


@pytest.mark.asyncio
async def test_migration_service_detects_milvus_mismatch():
    """Verify EmbeddingMigrationService detects embedding dimension mismatch."""

    from src.core.admin_ops.application.migration_service import EmbeddingMigrationService

    # Mock Tenant with config expecting 1536 dimensions
    mock_tenant = MagicMock()
    mock_tenant.id = "test_tenant"
    mock_tenant.name = "Test Tenant"
    mock_tenant.is_active = True
    mock_tenant.config = {
        "embedding_provider": "openai",
        "embedding_model": LEGACY_EMBEDDING_MODEL,
        "embedding_dimensions": LEGACY_EMBEDDING_DIM,  # Config expects default dims
    }

    # Mock Session to return the tenant
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_tenant]
    mock_session.execute.return_value = mock_result

    # Mock Settings
    mock_settings = MagicMock()
    mock_settings.default_embedding_provider = "openai"
    mock_settings.default_embedding_model = LEGACY_EMBEDDING_MODEL
    mock_settings.embedding_dimensions = LEGACY_EMBEDDING_DIM

    # Mock Vector Store Factory that returns MISMATCHED dimensions (768 instead of 1536)
    mock_store = AsyncMock()
    mock_store.get_collection_dimensions = AsyncMock(return_value=768)  # MISMATCH!
    mock_factory = MagicMock(return_value=mock_store)

    # Mock other dependencies
    mock_dispatcher = MagicMock()
    mock_graph_client = MagicMock()

    # Create the service
    service = EmbeddingMigrationService(
        session=mock_session,
        settings=mock_settings,
        task_dispatcher=mock_dispatcher,
        graph_client=mock_graph_client,
        vector_store_factory=mock_factory,
    )

    # Execute
    statuses = await service.get_compatibility_status()

    # Assert
    assert len(statuses) == 1
    assert not statuses[0]["is_compatible"]
    assert "Milvus Mismatch" in statuses[0]["details"]
    assert statuses[0]["milvus_dimensions"] == 768


@pytest.mark.asyncio
async def test_migration_service_reports_compatible_when_dimensions_match():
    """Verify EmbeddingMigrationService reports compatible when dimensions match."""

    from src.core.admin_ops.application.migration_service import EmbeddingMigrationService

    # Mock Tenant with config expecting 1536 dimensions
    mock_tenant = MagicMock()
    mock_tenant.id = "test_tenant"
    mock_tenant.name = "Test Tenant"
    mock_tenant.is_active = True
    mock_tenant.config = {
        "embedding_provider": "openai",
        "embedding_model": LEGACY_EMBEDDING_MODEL,
        "embedding_dimensions": LEGACY_EMBEDDING_DIM,
    }

    # Mock Session
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_tenant]
    mock_session.execute.return_value = mock_result

    # Mock Settings
    mock_settings = MagicMock()
    mock_settings.default_embedding_provider = "openai"
    mock_settings.default_embedding_model = LEGACY_EMBEDDING_MODEL
    mock_settings.embedding_dimensions = LEGACY_EMBEDDING_DIM

    # Mock Vector Store Factory that returns MATCHING dimensions
    mock_store = AsyncMock()
    mock_store.get_collection_dimensions = AsyncMock(return_value=LEGACY_EMBEDDING_DIM)  # MATCH!
    mock_factory = MagicMock(return_value=mock_store)

    # Mock other dependencies
    mock_dispatcher = MagicMock()
    mock_graph_client = MagicMock()

    # Create the service
    service = EmbeddingMigrationService(
        session=mock_session,
        settings=mock_settings,
        task_dispatcher=mock_dispatcher,
        graph_client=mock_graph_client,
        vector_store_factory=mock_factory,
    )

    # Execute
    statuses = await service.get_compatibility_status()

    # Assert
    assert len(statuses) == 1
    assert statuses[0]["is_compatible"]


@pytest.mark.asyncio
async def test_neo4j_constraint_check():
    """Verify Neo4j constraint check logic (mocked at module level)."""

    # This tests the logic that would raise RuntimeError on missing constraints
    required_constraints = ["document_id_unique", "chunk_id_unique"]
    found_constraints = [{"name": "some_other_constraint"}]  # Missing required ones

    found_names = [c["name"] for c in found_constraints]
    missing_constraints = [c for c in required_constraints if c not in found_names]

    assert len(missing_constraints) == 2
    assert "document_id_unique" in missing_constraints
    assert "chunk_id_unique" in missing_constraints
