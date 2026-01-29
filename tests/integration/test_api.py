import pytest
"""
Integration Tests for API Endpoints
====================================

Tests that require a running API server.
"""



@pytest.mark.asyncio
class TestHealthEndpoints:
    """Tests for health check endpoints."""

    async def test_liveness_returns_200(self, client):
        """Liveness endpoint should always return 200."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert "version" in data

    async def test_liveness_no_auth_required(self, client):
        """Liveness should not require authentication."""
        # No X-API-Key header
        response = await client.get("/health")
        assert response.status_code == 200

    async def test_readiness_structure(self, client):
        """Readiness should return dependency status."""
        response = await client.get("/health/ready")
        # Will likely be 503 without running services, but structure should be valid
        data = response.json()
        assert "status" in data
        assert "timestamp" in data
        assert "dependencies" in data


@pytest.mark.asyncio
class TestAuthentication:
    """Tests for authentication middleware."""

    async def test_protected_endpoint_no_key(self, client):
        """Protected endpoints should reject requests without API key."""
        response = await client.post("/v1/query", json={"query": "test"})
        assert response.status_code == 401
        data = response.json()
        assert data["error"]["code"] == "UNAUTHORIZED"

    async def test_protected_endpoint_invalid_key(self, client):
        """Protected endpoints should reject invalid API keys."""
        response = await client.post(
            "/v1/query",
            json={"query": "test"},
            headers={"X-API-Key": "invalid_key"},
        )
        assert response.status_code == 401

    async def test_protected_endpoint_valid_key(self, client, api_key):
        """Protected endpoints should accept valid API keys."""
        response = await client.post(
            "/v1/query",
            json={"query": "test"},
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 200


@pytest.mark.asyncio
class TestQueryEndpoint:
    """Tests for query API endpoint."""

    async def test_query_returns_structured_response(self, client, api_key):
        """Query should return properly structured response."""
        response = await client.post(
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

    async def test_query_with_trace(self, client, api_key):
        """Query with trace option should include trace steps."""
        response = await client.post(
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

    async def test_query_validation(self, client, api_key):
        """Query should validate input."""
        # Empty query
        response = await client.post(
            "/v1/query",
            json={"query": ""},
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 422

        # Missing query
        response = await client.post(
            "/v1/query",
            json={},
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 422


@pytest.mark.asyncio
class TestDocumentEndpoints:
    """Tests for document API endpoints."""

    async def test_upload_document(self, client, api_key):
        """Document upload should work with proper multipart form data."""
        # The endpoint now requires a file upload (multipart/form-data)
        # Without a file, it should return 422 (validation error)
        response = await client.post(
            "/v1/documents",
            headers={"X-API-Key": api_key},
        )
        # Accept 422 (missing file) or 400 (bad request)
        assert response.status_code in (400, 422)

    async def test_list_documents(self, client, api_key):
        """Document list endpoint is now implemented."""
        response = await client.get(
            "/v1/documents",
            headers={"X-API-Key": api_key},
        )
        # The endpoint is now implemented, should return 200
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


@pytest.mark.asyncio
class TestRequestHeaders:
    """Tests for request/response headers."""

    async def test_request_id_generated(self, client, api_key):
        """Responses should include X-Request-ID header."""
        response = await client.post(
            "/v1/query",
            json={"query": "test"},
            headers={"X-API-Key": api_key},
        )
        assert "X-Request-ID" in response.headers
        assert response.headers["X-Request-ID"].startswith("req_")

    async def test_request_id_preserved(self, client, api_key):
        """Client-provided request IDs should be preserved."""
        client_id = "550e8400-e29b-41d4-a716-446655440000"
        response = await client.post(
            "/v1/query",
            json={"query": "test"},
            headers={
                "X-API-Key": api_key,
                "X-Request-ID": client_id,
            },
        )
        assert response.headers["X-Request-ID"] == client_id

    async def test_timing_header(self, client, api_key):
        """Responses should include timing header."""
        response = await client.post(
            "/v1/query",
            json={"query": "test"},
            headers={"X-API-Key": api_key},
        )
        assert "X-Response-Time-Ms" in response.headers

    async def test_rate_limit_headers(self, client, api_key):
        """Responses should include rate limit headers."""
        response = await client.post(
            "/v1/query",
            json={"query": "test"},
            headers={"X-API-Key": api_key},
        )
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers
        assert "X-RateLimit-Reset" in response.headers


@pytest.mark.asyncio
class TestOpenAPI:
    """Tests for OpenAPI documentation."""

    async def test_docs_accessible(self, client):
        """OpenAPI docs should be accessible without auth."""
        response = await client.get("/docs")
        assert response.status_code == 200

    async def test_openapi_json(self, client):
        """OpenAPI JSON should be accessible."""
        response = await client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert data["info"]["title"] == "Amber API"
