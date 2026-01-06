"""
Hybrid GraphRAG API
===================

FastAPI application entry point.
Configures middleware, routes, and exception handlers.
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.config import settings
from src.api.middleware.auth import AuthenticationMiddleware
from src.api.middleware.exceptions import register_exception_handlers
from src.api.middleware.rate_limit import RateLimitMiddleware, UploadSizeLimitMiddleware
from src.api.middleware.request_id import RequestIdMiddleware
from src.api.middleware.timing import TimingMiddleware

# from src.core.observability.tracer import setup_tracer
# from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
# Import core routes (always available)
from src.api.routes import health, query

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Handles startup and shutdown events.
    """
    # Startup
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    logger.info(f"Debug mode: {settings.debug}")

    # SAFETY WARNING
    if os.getenv("AMBER_RUNTIME") != "docker":
        logger.warning("! " * 40)
        logger.warning("HOST EXECUTION DETECTED")
        logger.warning(f"You are running {settings.app_name} on the HOST machine.")
        logger.warning("Ensure your local environment matches Docker (DBs, config, etc).")
        logger.warning("! " * 40)

    # Initialize Tracing
    # setup_tracer(service_name=settings.app_name)

    yield

    # Shutdown
    logger.info("Shutting down...")
    # Close rate limiter Redis connection
    try:
        from src.core.rate_limiter import rate_limiter
        await rate_limiter.close()
    except Exception as e:
        logger.warning(f"Error closing rate limiter: {e}")


# =============================================================================
# Create FastAPI Application
# =============================================================================

app = FastAPI(
    title="Amber API",
    description="""
    **Amber — Preserving Context, Revealing Insight**

    This API provides access to a hybrid retrieval system that combines
    vector similarity search with knowledge graph reasoning to deliver
    contextual, sourced, and high-quality answers over document collections.

    ## Features

    - **Document Ingestion**: Upload and process multi-format documents
    - **Hybrid Retrieval**: Combine vector and graph-based search
    - **Augmented Generation**: Generate grounded answers with citations
    - **Full Observability**: Track every stage of processing

    ## Authentication

    All endpoints (except health checks) require an API key.
    Pass your key in the `X-API-Key` header.
    """,
    version=settings.app_version,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=[
        {
            "name": "health",
            "description": "Health check endpoints for liveness and readiness probes",
        },
        {
            "name": "query",
            "description": "Query the knowledge base and get answers",
        },
        {
            "name": "documents",
            "description": "Document upload, management, and retrieval",
        },
    ],
    lifespan=lifespan,
)

# Instrument app with OpenTelemetry
# FastAPIInstrumentor.instrument_app(app)

# =============================================================================
# Register Middleware (order matters - first registered = outermost)
# =============================================================================

# CORS middleware (outermost)
cors_origins = settings.cors_origins or ["*"]
allow_credentials = "*" not in cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Timing middleware (measure total request time)
app.add_middleware(TimingMiddleware)

# Request ID middleware (generate/propagate request IDs)
app.add_middleware(RequestIdMiddleware)

# Upload size limit middleware
app.add_middleware(UploadSizeLimitMiddleware)

# Authentication middleware (innermost - runs after rate limiting)
# Middleware is applied in reverse order of addition.
# We want: Request -> RateLimit -> Auth -> Routes
# So we must add Auth first (inner), them RateLimit (outer).
app.add_middleware(AuthenticationMiddleware)

# Rate limiting middleware
app.add_middleware(RateLimitMiddleware)

# =============================================================================
# Register Exception Handlers
# =============================================================================

register_exception_handlers(app)

# =============================================================================
# Register Routes
# =============================================================================

# Health endpoints (no prefix, no auth required)
app.include_router(health.router)
# Also mount under /api for frontend proxies that prefix everything
app.include_router(health.router, prefix="/api")

# API v1 routes
# from fastapi import APIRouter # Moved to top

v1_router = APIRouter(prefix="/v1")

# Core routes (always available)
v1_router.include_router(query.router)

# Optional routes (require database/Phase 1 dependencies)
try:
    from src.api.routes import documents
    v1_router.include_router(documents.router)
    logger.info("Registered documents router")
except ImportError as e:
    logger.warning(f"Documents router not available: {e}")

try:
    from src.api.routes import chunks
    v1_router.include_router(chunks.router)
    logger.info("Registered chunks router")
except ImportError as e:
    logger.warning(f"Chunks router not available: {e}")

try:
    from src.api.routes import events
    v1_router.include_router(events.router)
    logger.info("Registered events router")
except ImportError as e:
    logger.warning(f"Events router not available: {e}")

try:
    from src.api.routes import communities
    v1_router.include_router(communities.router)
    logger.info("Registered communities router")
except ImportError as e:
    logger.warning(f"Communities router not available: {e}")

try:
    from src.api.routes import feedback
    v1_router.include_router(feedback.router)
    logger.info("Registered feedback router")
except ImportError as e:
    logger.warning(f"Feedback router not available: {e}")

try:
    from src.api.routes import connectors
    v1_router.include_router(connectors.router)
    logger.info("Registered connectors router")
except ImportError as e:
    logger.warning(f"Connectors router not available: {e}")

try:
    from src.api.routes import seed
    v1_router.include_router(seed.router)
    logger.info("Registered seed router")
except ImportError as e:
    logger.warning(f"Seed router not available: {e}")

# Phase 10: Admin routes
try:
    from src.api.routes.admin import router as admin_router
    v1_router.include_router(admin_router)
    logger.info("Registered admin router")
except ImportError as e:
    logger.warning(f"Admin router not available: {e}")

# Setup routes (for on-demand dependency installation)
try:
    from src.api.routes import setup
    app.include_router(setup.router)  # Register at root level, not under /v1
    logger.info("Registered setup router")
except ImportError as e:
    logger.warning(f"Setup router not available: {e}")

app.include_router(v1_router)


# =============================================================================
# Root Endpoint
# =============================================================================


@app.get("/", include_in_schema=False)
async def root():
    """Root endpoint - redirects to docs."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/health",
    }
