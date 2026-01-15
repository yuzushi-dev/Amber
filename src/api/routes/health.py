"""
Health Check Endpoints
======================

Provides liveness and readiness probes for the API.
These endpoints do NOT require authentication.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, status
from pydantic import BaseModel

from src.api.config import settings
from src.core.health import health_checker

router = APIRouter(prefix="/health", tags=["health"])


# =============================================================================
# Response Models
# =============================================================================


class LivenessResponse(BaseModel):
    """Liveness probe response."""

    status: str
    timestamp: str
    version: str


class DependencyStatus(BaseModel):
    """Individual dependency status."""

    status: str
    latency_ms: float | None = None
    error: str | None = None


class ReadinessResponse(BaseModel):
    """Readiness probe response with dependency status."""

    status: str
    timestamp: str
    dependencies: dict[str, DependencyStatus]


# =============================================================================
# Endpoints
# =============================================================================


@router.get(
    "",
    response_model=LivenessResponse,
    status_code=status.HTTP_200_OK,
    summary="Liveness Probe",
    description="Returns 200 if the process is alive. Used by Kubernetes liveness probes.",
)
async def liveness() -> LivenessResponse:
    """
    Liveness probe endpoint.

    This endpoint always returns 200 if the process is running.
    It does NOT check dependencies - that's what readiness is for.

    Returns:
        LivenessResponse: Basic health status
    """
    return LivenessResponse(
        status="healthy",
        timestamp=datetime.now(UTC).isoformat(),
        version=settings.app_version,
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={
        200: {"description": "All dependencies healthy"},
        503: {"description": "One or more dependencies unhealthy"},
    },
    summary="Readiness Probe",
    description="Checks all dependencies and returns their status. Used by Kubernetes readiness probes. Pass ?silent=true to get 200 OK even if unhealthy (useful for frontend polling).",
)
async def readiness(silent: bool = False) -> ReadinessResponse:
    """
    Readiness probe endpoint.

    Checks all system dependencies:
    - PostgreSQL
    - Redis
    - Neo4j
    - Milvus

    Returns 200 if all dependencies are healthy.
    Returns 503 if any dependency is unhealthy.

    Returns:
        ReadinessResponse: Detailed dependency status
    """
    try:
        system_health = await health_checker.check_all()
        
        # Convert to response model
        dependencies: dict[str, DependencyStatus] = {}
        for name, dep in system_health.dependencies.items():
            dependencies[name] = DependencyStatus(
                status=dep.status.value,
                latency_ms=dep.latency_ms,
                error=dep.error,
            )

        response = ReadinessResponse(
            status="ready" if system_health.is_healthy else "unhealthy",
            timestamp=datetime.now(UTC).isoformat(),
            dependencies=dependencies,
        )
    except Exception as e:
        # Fallback if health checker itself fails (e.g. startup race conditions)
        from src.core.health import HealthStatus # Import locally to avoid circulars if needed
        
        response = ReadinessResponse(
            status="unhealthy",
            timestamp=datetime.now(UTC).isoformat(),
            dependencies={
                "system": DependencyStatus(
                    status="down",
                    error=f"Health check failed: {str(e)}"
                )
            }
        )
        system_health = None # Marker that it failed

    # Note: We return the response with appropriate status code
    # The actual status code is set by the route decorator's responses
    # FastAPI will use 200 by default, we need to raise for 503
    is_healthy = system_health.is_healthy if system_health else False
    
    if not is_healthy and not silent:
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=response.model_dump(),
        )

    return response
