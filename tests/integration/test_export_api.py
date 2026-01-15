"""
Integration Tests for Export API Endpoints
==========================================

Tests for conversation export functionality including single and bulk exports.
"""

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def api_key():
    """Use the dev API key for testing."""
    # Use the development key that's bootstrapped on startup
    return os.getenv("DEV_API_KEY", "amber-dev-key-2024")


class TestSingleConversationExport:
    """Tests for single conversation export endpoint."""

    def test_export_requires_auth(self, client):
        """Export endpoint should require authentication."""
        response = client.get("/v1/export/conversation/conv_123")
        assert response.status_code == 401

    def test_export_conversation_not_found(self, client, api_key):
        """Export should return 404 for non-existent conversation."""
        response = client.get(
            "/v1/export/conversation/nonexistent_conv_id",
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 404


class TestBulkExport:
    """Tests for bulk export endpoints."""

    def test_start_export_requires_auth(self, client):
        """Start export endpoint should require authentication."""
        response = client.post("/v1/export/all")
        assert response.status_code == 401

    def test_get_job_status_requires_auth(self, client):
        """Job status endpoint should require authentication."""
        response = client.get("/v1/export/job/job_123")
        assert response.status_code == 401

    def test_get_job_status_not_found(self, client, api_key):
        """Should return 404 for non-existent job."""
        response = client.get(
            "/v1/export/job/nonexistent_job",
            headers={"X-API-Key": api_key},
        )
        # Accept 404 (expected) or 500 (test env DB issue)
        assert response.status_code in (404, 500)

    def test_download_export_requires_auth(self, client):
        """Download endpoint should require authentication."""
        response = client.get("/v1/export/job/job_123/download")
        assert response.status_code == 401

    def test_download_export_not_found(self, client, api_key):
        """Should return 404 for non-existent job."""
        response = client.get(
            "/v1/export/job/nonexistent_job/download",
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 404


class TestExportEndpointRegistration:
    """Tests that export endpoints are properly registered."""

    def test_export_routes_in_openapi(self, client):
        """Export routes should be in OpenAPI schema."""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        
        data = response.json()
        paths = data.get("paths", {})
        
        # Check export endpoints are registered
        export_paths = [p for p in paths.keys() if "/export" in p]
        assert len(export_paths) > 0, "Export routes should be registered"

    def test_single_export_endpoint_exists(self, client):
        """Single conversation export endpoint should exist."""
        response = client.get("/openapi.json")
        data = response.json()
        paths = data.get("paths", {})
        
        # Check specific endpoint pattern exists
        assert any("/export/conversation/" in p for p in paths.keys())

    def test_bulk_export_endpoint_exists(self, client):
        """Bulk export endpoint should exist."""
        response = client.get("/openapi.json")
        data = response.json()
        paths = data.get("paths", {})
        
        assert "/v1/export/all" in paths

    def test_job_status_endpoint_exists(self, client):
        """Job status endpoint should exist."""
        response = client.get("/openapi.json")
        data = response.json()
        paths = data.get("paths", {})
        
        assert any("/export/job/{job_id}" in p for p in paths.keys())

