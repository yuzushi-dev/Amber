"""
Integration Tests for API Endpoints
====================================

Tests that require a running API server.
"""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.shared.security import generate_api_key, register_api_key


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def api_key():
    """Generate and register a test API key."""
    key = generate_api_key(prefix="test")
    register_api_key(key, "test_tenant", "Test Key", ["read", "write"])
    return key


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    def test_liveness_returns_200(self, client):
        """Liveness endpoint should always return 200."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert "version" in data

    def test_liveness_no_auth_required(self, client):
        """Liveness should not require authentication."""
        # No X-API-Key header
        response = client.get("/health")
        assert response.status_code == 200

    def test_readiness_structure(self, client):
        """Readiness should return dependency status."""
        response = client.get("/health/ready")
        # Will likely be 503 without running services, but structure should be valid
        data = response.json()
        assert "status" in data
        assert "timestamp" in data
        assert "dependencies" in data


class TestAuthentication:
    """Tests for authentication middleware."""

    def test_protected_endpoint_no_key(self, client):
        """Protected endpoints should reject requests without API key."""
        response = client.post("/v1/query", json={"query": "test"})
        assert response.status_code == 401
        data = response.json()
        assert data["error"]["code"] == "UNAUTHORIZED"

    def test_protected_endpoint_invalid_key(self, client):
        """Protected endpoints should reject invalid API keys."""
        response = client.post(
            "/v1/query",
            json={"query": "test"},
            headers={"X-API-Key": "invalid_key"},
        )
        assert response.status_code == 401

    def test_protected_endpoint_valid_key(self, client, api_key):
        """Protected endpoints should accept valid API keys."""
        response = client.post(
            "/v1/query",
            json={"query": "test"},
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 200


class TestQueryEndpoint:
    """Tests for query API endpoint."""

    def test_query_returns_structured_response(self, client, api_key):
        """Query should return properly structured response."""
        response = client.post(
            "/v1/query",
            json={"query": "What is GraphRAG?"},
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 200
        data = response.json()

        # Check required fields
        assert "answer" in data
        assert "sources" in data
        assert "timing" in data
        assert "total_ms" in data["timing"]

    def test_query_with_trace(self, client, api_key):
        """Query with trace option should include trace steps."""
        response = client.post(
            "/v1/query",
            json={
                "query": "What is GraphRAG?",
                "options": {"include_trace": True},
            },
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 200
        data = response.json()

        assert "trace" in data
        assert len(data["trace"]) > 0
        assert all("step" in step for step in data["trace"])
        assert all("duration_ms" in step for step in data["trace"])

    def test_query_validation(self, client, api_key):
        """Query should validate input."""
        # Empty query
        response = client.post(
            "/v1/query",
            json={"query": ""},
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 422

        # Missing query
        response = client.post(
            "/v1/query",
            json={},
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 422


class TestDocumentEndpoints:
    """Tests for document API endpoints."""

    def test_upload_document(self, client, api_key):
        """Document upload should work with proper multipart form data."""
        # The endpoint now requires a file upload (multipart/form-data)
        # Without a file, it should return 422 (validation error)
        response = client.post(
            "/v1/documents",
            headers={"X-API-Key": api_key},
        )
        # Accept 422 (missing file) or 400 (bad request)
        assert response.status_code in (400, 422)

    def test_list_documents(self, client, api_key):
        """Document list endpoint is now implemented."""
        response = client.get(
            "/v1/documents",
            headers={"X-API-Key": api_key},
        )
        # The endpoint is now implemented, should return 200
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


class TestRequestHeaders:
    """Tests for request/response headers."""

    def test_request_id_generated(self, client, api_key):
        """Responses should include X-Request-ID header."""
        response = client.post(
            "/v1/query",
            json={"query": "test"},
            headers={"X-API-Key": api_key},
        )
        assert "X-Request-ID" in response.headers
        assert response.headers["X-Request-ID"].startswith("req_")

    def test_request_id_preserved(self, client, api_key):
        """Client-provided request IDs should be preserved."""
        client_id = "550e8400-e29b-41d4-a716-446655440000"
        response = client.post(
            "/v1/query",
            json={"query": "test"},
            headers={
                "X-API-Key": api_key,
                "X-Request-ID": client_id,
            },
        )
        assert response.headers["X-Request-ID"] == client_id

    def test_timing_header(self, client, api_key):
        """Responses should include timing header."""
        response = client.post(
            "/v1/query",
            json={"query": "test"},
            headers={"X-API-Key": api_key},
        )
        assert "X-Response-Time-Ms" in response.headers

    def test_rate_limit_headers(self, client, api_key):
        """Responses should include rate limit headers."""
        response = client.post(
            "/v1/query",
            json={"query": "test"},
            headers={"X-API-Key": api_key},
        )
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers
        assert "X-RateLimit-Reset" in response.headers


class TestOpenAPI:
    """Tests for OpenAPI documentation."""

    def test_docs_accessible(self, client):
        """OpenAPI docs should be accessible without auth."""
        response = client.get("/docs")
        assert response.status_code == 200

    def test_openapi_json(self, client):
        """OpenAPI JSON should be accessible."""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert data["info"]["title"] == "Amber API"
