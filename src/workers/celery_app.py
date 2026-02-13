"""
Celery Application Configuration
================================

Configures Celery for background task processing.
"""

import asyncio
import logging
import os
import sys

from celery import Celery
from celery.signals import worker_process_init, worker_ready

from src.shared.kernel.runtime import configure_settings

logger = logging.getLogger(__name__)
# =============================================================================
# SAFETY GUARDRAIL
# =============================================================================
# Prevent accidental host execution of worker implementation
try:
    _is_worker = "worker" in sys.argv
    _is_docker = os.getenv("AMBER_RUNTIME") == "docker"
    _force_local = os.getenv("AMBER_FORCE_LOCAL") == "true"

    if _is_worker and not _is_docker and not _force_local:
        print("\n" + "!" * 80)
        print("CRITICAL SAFETY ERROR: HOST EXECUTION BLOCKED")
        print("!" * 80)
        print("You are attempting to run the Celery worker directly on the host machine.")
        print("This causes STALE CODE execution, race conditions, and debugging nightmares.")
        print("\nSolution:")
        print("  1. USE DOCKER: docker compose up worker")
        print("  2. BYPASS (Debug only): AMBER_FORCE_LOCAL=true celery -A ... worker")
        print("!" * 80 + "\n")
        sys.exit(1)
except Exception:
    pass  # Fallback for weird edge cases, though sys.exit should happen


# ... imports

# Celery configuration
broker_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")

# Create Celery app
celery_app = Celery(
    "graphrag",
    broker=broker_url,
    backend=result_backend,
    include=[
        "src.workers.tasks",
        "src.workers.export_tasks",
        "src.workers.backup_tasks",
    ],
)

# Configure Celery
celery_app.conf.update(
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Worker settings
    worker_prefetch_multiplier=1,
    worker_concurrency=2,
    # Task execution settings
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Result settings
    result_expires=3600,  # 1 hour
    # Retry settings
    task_default_retry_delay=60,
    task_max_retries=3,
    # EAGER MODE: Execute tasks synchronously (for testing)
    task_always_eager=os.getenv("CELERY_TASK_ALWAYS_EAGER", "").lower() in ("true", "1", "yes"),
    task_eager_propagates=True,  # Propagate exceptions in eager mode
)

# Task routing (optional, can be configured later)
celery_app.conf.task_routes = {
    "src.workers.tasks.process_document": {"queue": "high_priority"},
    "src.workers.tasks.process_communities": {"queue": "low_priority"},
    "src.workers.tasks.ingestion.*": {"queue": "ingestion"},
    "src.workers.tasks.extraction.*": {"queue": "extraction"},
    "src.workers.tasks.run_ragas_benchmark": {"queue": "evaluation"},
    # export_tasks uses default celery queue
}


@worker_process_init.connect
def init_worker_process(**kwargs):
    """Initialize providers and other dependencies when worker process starts.

    Uses worker_process_init instead of worker_init because prefork pool
    requires each forked process to initialize its own resources.
    """
    logger.info("Initializing worker process providers...")
    try:
        from src.api.config import settings
        from src.core.generation.infrastructure.providers.factory import init_providers

        configure_settings(settings)
        _initialize_worker_runtime(settings=settings, init_providers=init_providers)
        logger.info("Worker process providers initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize worker providers: {e}")
        # Don't fail worker startup - some tasks may not need providers


def _initialize_worker_runtime(settings, init_providers):
    """Initialize runtime dependencies required by worker tasks."""
    from src.core.database.session import configure_database

    configure_database(settings.db.database_url)

    from src.amber_platform.composition_root import platform

    asyncio.run(platform.initialize())

    providers = getattr(settings, "providers", None)
    openai_key = getattr(providers, "openai_api_key", None) or settings.openai_api_key
    anthropic_key = getattr(providers, "anthropic_api_key", None) or settings.anthropic_api_key

    # Initialize providers with API keys from settings
    init_providers(
        openai_api_key=openai_key,
        anthropic_api_key=anthropic_key,
        ollama_base_url=settings.ollama_base_url,
        default_llm_provider=settings.default_llm_provider,
        default_llm_model=settings.default_llm_model,
        default_embedding_provider=settings.default_embedding_provider,
        default_embedding_model=settings.default_embedding_model,
        llm_fallback_local=settings.llm_fallback_local,
        llm_fallback_economy=settings.llm_fallback_economy,
        llm_fallback_standard=settings.llm_fallback_standard,
        llm_fallback_premium=settings.llm_fallback_premium,
        embedding_fallback_order=settings.embedding_fallback_order,
    )


@worker_ready.connect
def on_worker_ready(**kwargs):
    """Run stale document recovery when worker is fully ready.

    This signal fires after all worker initialization is complete,
    making it safe to access databases and other resources.
    """
    logger.info("Worker ready - checking for stale documents...")
    try:
        from src.workers.recovery import run_recovery_sync

        result = run_recovery_sync()

        if result.get("total", 0) > 0:
            logger.info(
                f"Stale document recovery: {result.get('recovered', 0)} recovered, "
                f"{result.get('failed', 0)} failed out of {result.get('total', 0)}"
            )
        else:
            logger.info("No stale documents found")

    except Exception as e:
        logger.error(f"Stale document recovery failed: {e}")
        # Don't fail worker startup - recovery is best-effort
