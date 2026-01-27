"""
Hybrid GraphRAG API
===================

FastAPI application entry point.
Configures middleware, routes, and exception handlers.
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.config import settings
from src.api.middleware.auth import AuthenticationMiddleware
from src.api.middleware.exceptions import register_exception_handlers
from src.api.middleware.rate_limit import RateLimitMiddleware, UploadSizeLimitMiddleware
from src.api.middleware.request_id import RequestIdMiddleware
from src.api.middleware.timing import TimingMiddleware

# from src.core.admin_ops.infrastructure.observability.tracer import setup_tracer
# from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
# Import core routes (always available)
from src.api.routes import health, query

from src.core.admin_ops.infrastructure.observability.logging import configure_logging
from src.core.admin_ops.infrastructure.observability.middleware import StructuredLoggingMiddleware
from src.api.routes.admin import observability
from src.shared.kernel.runtime import configure_settings

# Configure logging (JSON in prod, text in dev usually, but forcing JSON for consistency if needed or use arg)
configure_logging(log_level=settings.log_level, json_format=os.getenv("LOG_FORMAT", "json") == "json")
logger = logging.getLogger(__name__)


def _configure_runtime_settings() -> None:
    configure_settings(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Handles startup and shutdown events.
    """
    # Startup
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    logger.info(f"Debug mode: {settings.debug}")
    _configure_runtime_settings()

    # Initialize Platform Clients (Neo4j, Redis, MinIO)
    try:
        from src.amber_platform.composition_root import platform
        await platform.initialize()
        logger.info("Platform clients initialized")
    except Exception as e:
        logger.error(f"Failed to initialize platform clients: {e}")

    # Initialize LLM Providers
    try:
        from src.core.generation.infrastructure.providers.factory import init_providers
        init_providers(
            openai_api_key=settings.openai_api_key,
            anthropic_api_key=settings.anthropic_api_key,
            ollama_base_url=settings.ollama_base_url,
            default_llm_provider=settings.default_llm_provider,
            default_llm_model=settings.default_llm_model,
            default_embedding_provider=settings.default_embedding_provider,
            default_embedding_model=settings.default_embedding_model,
        )
        logger.info("LLM Providers initialized")
    except Exception as e:
        logger.error(f"Failed to initialize LLM providers: {e}")

    # Initialize Shared Security
    try:
        from src.shared.security import configure_security
        configure_security(settings.secret_key)
        logger.info("Security module configured")
    except Exception as e:
        logger.error(f"Failed to configure security: {e}")

    # Initialize Database
    try:
        from src.core.database.session import configure_database
        configure_database(
            database_url=settings.db.database_url,
            pool_size=settings.db.pool_size,
            max_overflow=settings.db.max_overflow,
        )
        logger.info("Database module configured")
    except Exception as e:
        logger.error(f"Failed to configure database: {e}")

    # SAFETY WARNING
    if os.getenv("AMBER_RUNTIME") != "docker":
        logger.warning("! " * 40)
        logger.warning("HOST EXECUTION DETECTED")
        logger.warning(f"You are running {settings.app_name} on the HOST machine.")
        logger.warning("Ensure your local environment matches Docker (DBs, config, etc).")
        logger.warning("! " * 40)

    # Initialize Tracing
    # setup_tracer(service_name=settings.app_name)

    # Pre-warm SPLADE model for hybrid search (blocking to ensure readiness)
    # This ensures the API doesn't accept traffic until models are ready
    import asyncio
    try:
        from src.core.retrieval.application.sparse_embeddings_service import SparseEmbeddingService
        service = SparseEmbeddingService()
        await asyncio.to_thread(service.prewarm)
        logger.info("SPLADE model pre-warming complete - API ready")
    except Exception as e:
        logger.warning(f"Failed to prewarm SPLADE model: {e}")

    # Bootstrap API Key
    try:
        from src.api.deps import _get_async_session_maker
        from src.amber_platform.composition_root import platform, build_vector_store_factory
        from src.core.admin_ops.application.api_key_service import ApiKeyService
        from src.core.admin_ops.application.migration_service import EmbeddingMigrationService
        from src.infrastructure.adapters.celery_dispatcher import CeleryTaskDispatcher

        dev_key = os.getenv("DEV_API_KEY", "amber-dev-key-2024")
        
        # S01: Security Warning for Default Key
        if dev_key == "amber-dev-key-2024":
            logger.critical("!" * 60)
            logger.critical("SECURITY WARNING: Using default development API key.")
            logger.critical("Set DEV_API_KEY environment variable in production!")
            logger.critical("!" * 60)

        async with _get_async_session_maker()() as session:
            # Bootstrap Key
            service = ApiKeyService(session)
            await service.ensure_bootstrap_key(dev_key, name="Development Key")

            # Check Embedding Compatibility
            if os.getenv("AMBER_RUNTIME") == "docker": # Only run inside docker/prod context usually
                vector_store_factory = build_vector_store_factory()
                migration_service = EmbeddingMigrationService(
                    session=session,
                    settings=settings,
                    task_dispatcher=CeleryTaskDispatcher(),
                    graph_client=platform.neo4j_client,
                    vector_store_factory=vector_store_factory,
                )
                try:
                    statuses = await migration_service.get_compatibility_status()
                    incompatible = [s for s in statuses if not s["is_compatible"]]
                    
                    if incompatible:
                        logger.critical("!" * 80)
                        logger.critical("EMBEDDING MODEL MISMATCH DETECTED")
                        logger.critical("!" * 80)
                        for status in incompatible:
                            logger.critical(f"TENANT: {status['tenant_name']} ({status['tenant_id']})")
                            logger.critical(f"  - Config: {status['stored_config'].get('model')} ({status['stored_config'].get('dimensions')}d)")
                            logger.critical(f"  - System: {status['system_config'].get('model')} ({status['system_config'].get('dimensions')}d)")
                            logger.critical(f"  - Error:  {status['details']}")
                        logger.critical("!" * 80)
                        logger.critical("Startup Aborted to prevent data corruption.")
                        logger.critical("To fix this:")
                        logger.critical("1. Update config/settings.yaml to match your data.")
                        logger.critical("2. OR Run 'python scripts/check_integrity.py' to diagnose.")
                        logger.critical("3. OR Set IGNORE_EMBEDDING_MISMATCH=true env var to force start.")
                        logger.critical("!" * 80)
                        
                        if os.getenv("IGNORE_EMBEDDING_MISMATCH", "false").lower() != "true":
                            raise RuntimeError("Embedding model mismatch detected. Aborting startup.")
                        else:
                            logger.warning("IGNORE_EMBEDDING_MISMATCH=true. Forced startup proceed.")

                except Exception as e:
                    if "Embedding model mismatch" in str(e):
                        raise
                    logger.error(f"Failed to check embedding compatibility on startup: {e}")

        logger.info("Bootstrapped API key and checked embeddings")
        
        # ---------------------------------------------------------
        # DB Integrity Check (Neo4j & Postgres)
        # ---------------------------------------------------------
        if os.getenv("IGNORE_DB_INTEGRITY", "false").lower() != "true":
            try:
                # 1. Neo4j Check
                from src.amber_platform.composition_root import platform
                # Check for critical constraints
                # This is a basic check. For detailed check, use scripts/check_integrity.py
                constraints_res = await platform.neo4j_client.execute_read("SHOW CONSTRAINTS")
                found_names = [c["name"] for c in constraints_res]
                
                required_constraints = ["document_id_unique", "chunk_id_unique"]
                missing_constraints = [c for c in required_constraints if c not in found_names]
                
                if missing_constraints:
                    logger.critical("!" * 80)
                    logger.critical("NEO4J INTEGRITY ERROR: Missing critical constraints!")
                    logger.critical(f"Missing: {missing_constraints}")
                    logger.critical("Please run the application setup or migration scripts.")
                    logger.critical("Or set IGNORE_DB_INTEGRITY=true to bypass.")
                    logger.critical("!" * 80)
                    raise RuntimeError("Neo4j constraints missing. Aborting startup.")

                # 2. Postgres Check (Alembic)
                # We need to run this in a thread because alembic commands are sync
                def check_alembic():
                    from alembic.config import Config
                    from alembic.script import ScriptDirectory
                    from sqlalchemy import text
                    
                    try:
                        alembic_cfg = Config("alembic.ini")
                        script = ScriptDirectory.from_config(alembic_cfg)
                        heads = script.get_heads()
                        head_rev = heads[0] if heads else None
                        return head_rev
                    except Exception as e:
                        logger.warning(f"Failed to read Alembic head: {e}")
                        return None
                
                head_rev = await asyncio.to_thread(check_alembic)
                
                if head_rev:
                    # Check DB version
                    from sqlalchemy import text
                    result = await session.execute(text("select version_num from alembic_version"))
                    db_rev = result.scalar()
                    
                    logger.info(f"Database Integrity: Code={head_rev}, DB={db_rev}")
                    
                    if head_rev != db_rev:
                        logger.critical("!" * 80)
                        logger.critical("DATABASE INTEGRITY ERROR: Schema Mismatch!")
                        logger.critical(f"Code expects revision {head_rev}, but DB is at {db_rev}")
                        logger.critical("Run 'alembic upgrade head' to fix this.")
                        logger.critical("Or set IGNORE_DB_INTEGRITY=true to bypass.")
                        logger.critical("!" * 80)
                        raise RuntimeError("Database schema mismatch. Aborting startup.")
                    
            except ImportError:
                 logger.warning("Alembic not installed or configuration missing. Skipping DB check.")
            except Exception as e:
                 # If we are failing, we fail safely if likely just setup issue? 
                 # User requested BLOCKER. So we re-raise.
                 if "Aborting startup" in str(e):
                     raise
                 logger.error(f"Integrity check failed: {e}")
                 # raise RuntimeError(f"Integrity check failed: {e}") # Maybe too strict if connectivity blip?
                 # Let's keep it strict but allow transient failures if it's not a clear mismatch?
                 # Actually, better to warn on unknown errors but fail on KNOWN mismatches.
                 pass
                 # Actually, better to warn on unknown errors but fail on KNOWN mismatches.
                 pass
    except Exception as e:
        # Re-raise critical integrity errors to ensure Fail Fast
        if "Aborting startup" in str(e) or "mismatch" in str(e):
             logger.critical(f"Critical Startup Error: {e}")
             raise
        logger.error(f"Failed to bootstrap API key: {e}")

    yield

    # Shutdown
    logger.info("Shutting down...")
    
    # helper for safe shutdown
    async def safe_shutdown(coro, name):
        try:
            await coro
        except Exception as e:
            logger.warning(f"Error closing {name}: {e}")

    # Close rate limiter Redis connection
    from src.api.middleware.rate_limit import _rate_limiter
    if _rate_limiter:
        await safe_shutdown(_rate_limiter.close(), "rate limiter")

    # Shutdown Platform Clients
    from src.amber_platform.composition_root import platform
    await safe_shutdown(platform.shutdown(), "platform clients")
    
    # Shutdown Database
    from src.core.database.session import close_database
    await safe_shutdown(close_database(), "database")


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

# Upload size limit middleware
app.add_middleware(UploadSizeLimitMiddleware)

# Authentication middleware (innermost - runs after rate limiting)
app.add_middleware(AuthenticationMiddleware)

# Rate limiting middleware
app.add_middleware(RateLimitMiddleware)

# Structured logging middleware (Trace requests with latency/status)
app.add_middleware(StructuredLoggingMiddleware)

# Timing middleware (measure total request time)
app.add_middleware(TimingMiddleware)

# Request ID middleware (generate/propagate request IDs - Outermost to ensure ID availability)
app.add_middleware(RequestIdMiddleware)

# =============================================================================
# Register Exception Handlers
# =============================================================================

register_exception_handlers(app)

# =============================================================================
# Register Routes
# =============================================================================

# API v1 routes
# from fastapi import APIRouter # Moved to top

v1_router = APIRouter(prefix="/v1")

# Core routes (always available)
v1_router.include_router(health.router)
v1_router.include_router(query.router)

# Auth routes
try:
    from src.api.routes import auth
    v1_router.include_router(auth.router)
    logger.info("Registered auth router")
except ImportError as e:
    logger.warning(f"Auth router not available: {e}")

# Chat routes (for history, etc.)
try:
    from src.api.routes import chat
    v1_router.include_router(chat.router)
    logger.info("Registered chat router")
except ImportError as e:
    logger.warning(f"Chat router not available: {e}")

# Optional routes (require database/Phase 1 dependencies)
try:
    from src.api.routes import documents
    v1_router.include_router(documents.router)
    logger.info("Registered documents router")
except ImportError as e:
    logger.warning(f"Documents router not available: {e}")

try:
    from src.api.routes import folders
    v1_router.include_router(folders.router, prefix="/folders", tags=["folders"])
    logger.info("Registered folders router")
except ImportError as e:
    logger.warning(f"Folders router not available: {e}")

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
    from src.api.routes import graph_editor
    v1_router.include_router(graph_editor.router)
    logger.info("Registered graph_editor router")
except ImportError as e:
    logger.warning(f"Graph Editor router not available: {e}")

try:
    from src.api.routes import graph_history
    v1_router.include_router(graph_history.router)
    logger.info("Registered graph_history router")
except ImportError as e:
    logger.warning(f"Graph History router not available: {e}")

try:
    v1_router.include_router(observability.router, prefix="/admin")
    logger.info("Registered observability router")
except Exception as e:
    logger.warning(f"Observability router registration failed: {e}")


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
    v1_router.include_router(setup.router)  # Move under /v1
    logger.info("Registered setup router")
except ImportError as e:
    logger.warning(f"Setup router not available: {e}")

# Export routes (conversation data export)
try:
    from src.api.routes import export
    v1_router.include_router(export.router)
    logger.info("Registered export router")
except ImportError as e:
    logger.warning(f"Export router not available: {e}")

# Also expose health check at root /health for infrastructure probes
app.include_router(health.router)

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
