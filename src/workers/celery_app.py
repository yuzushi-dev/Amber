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
from celery.signals import setup_logging, worker_process_init, worker_ready

from src.shared.kernel.runtime import configure_settings

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------------
# Celery Logging Hook
# -------------------------------------------------------------------------
# Celery's default behaviour is to *replace* the root logger config.
# We intercept the ``setup_logging`` signal so our structlog config wins.
# -------------------------------------------------------------------------
@setup_logging.connect
def _on_setup_logging(**kwargs):
    """Prevent Celery from overriding our structured logging."""
    from src.core.admin_ops.infrastructure.observability.logging import configure_logging

    configure_logging()
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
        "src.workers.provisioning_tasks",
        "src.workers.recovery",  # exposes periodic_recovery_sweep beat task
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
    # Recycle a worker process once it exceeds ~800 MiB RSS. The threshold is
    # per CHILD, and the prefork pool runs worker_concurrency=2 of them per
    # container, so the budget that must fit under the 2G per-replica cap
    # (docker-compose.yml) is 2 x this value, not one: 2 x 800 MiB = 1.6 GiB
    # leaves ~400 MiB for the master process and headroom. Gradual growth from
    # a heavy task (graph_extraction / community_summary during ingestion
    # fan-out) is reclaimed by a clean child restart BEFORE it hits the cgroup
    # limit, so we don't rely on OOM-kill + task requeue (which, with
    # task_acks_late + task_reject_on_worker_lost, risks a crash-restart loop on
    # a single oversized task). Note the check runs after a task completes, so
    # this bounds steady-state growth, not an intra-task spike.
    worker_max_memory_per_child=800_000,  # KiB (~800 MiB), x2 children = ~1.6 GiB
    # Task execution settings
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Time limits: soft raises SoftTimeLimitExceeded (catchable) at 1h; hard
    # SIGKILL at 2h.  Generous defaults let legitimate long ingestion/graph-sync
    # runs finish while still reaping truly-wedged tasks.
    # Per-task overrides: @task(time_limit=X, soft_time_limit=Y)
    task_soft_time_limit=3600,   # 1 hour
    task_time_limit=7200,        # 2 hours
    # Result settings
    result_expires=3600,  # 1 hour
    # Retry settings
    task_default_retry_delay=60,
    task_max_retries=3,
    # EAGER MODE: Execute tasks synchronously (for testing)
    task_always_eager=os.getenv("CELERY_TASK_ALWAYS_EAGER", "").lower() in ("true", "1", "yes"),
    task_eager_propagates=True,  # Propagate exceptions in eager mode
)

# Beat schedule (Celery Beat ticks; backup heartbeat scans BackupSchedule table)
celery_app.conf.beat_schedule = {
    "backup-heartbeat": {
        "task": "src.workers.backup_tasks.check_due_backups",
        "schedule": 60.0,  # seconds
    },
    # Periodic sweep for documents stuck in EXTRACTING/CLASSIFYING/CHUNKING/
    # EMBEDDING/GRAPH_SYNC while workers remain up (complements the boot-time
    # worker_ready recovery in on_worker_ready).
    "recovery-sweep": {
        "task": "src.workers.recovery.periodic_recovery_sweep",
        "schedule": 600.0,  # 10 minutes
    },
    # Periodic read-only sweep for stored `llm_steps` overrides drifting out of
    # sync with the live model registry (e.g. a provider retiring a model that
    # was valid when a tenant's config was last written). Complements the
    # write-time validation in validate_llm_step_override (applied on the
    # tenant config PUT), which only catches drift introduced at write time.
    "llm-registry-drift": {
        "task": "src.workers.tasks.check_llm_registry_drift",
        "schedule": 900.0,  # 15 minutes
    },
}

# Task routing
# NOTE: The "ingestion" and "extraction" queue globs were removed — no task is
# actually named under the src.workers.tasks.ingestion.* or .extraction.*
# namespaces (real task names are process_document, process_communities, etc.),
# so those routes were dead config and the "ingestion"/"extraction" queues never
# received work.  The worker -Q list and cancel-all queue list have been updated
# to match.
celery_app.conf.task_routes = {
    "src.workers.tasks.process_document": {"queue": "high_priority"},
    "src.workers.tasks.process_communities": {"queue": "low_priority"},
    "src.workers.tasks.run_ragas_benchmark": {"queue": "evaluation"},
    # export_tasks uses default celery queue
    "src.workers.provisioning_tasks.provision_tenant": {"queue": "low_priority"},
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
        openrouter_api_key=settings.openrouter_api_key,
        openrouter_base_url=settings.openrouter_base_url,
        nvidia_nim_api_key=settings.nvidia_nim_api_key,
        nvidia_nim_base_url=settings.nvidia_nim_base_url,
        llm_fallback_enabled=settings.llm_fallback_enabled,
        ollama_cloud_base_url=settings.ollama_cloud_base_url,
        ollama_cloud_api_keys=settings.ollama_cloud_api_keys,
    )


@worker_ready.connect
def on_worker_ready(**kwargs):
    """Run stale document recovery when worker is fully ready.

    This signal fires after all worker initialization is complete,
    making it safe to access databases and other resources.

    Deliberately no min_age_minutes override: the signal fires once per replica,
    so with `replicas: 3` a restarting replica must not touch what the others are
    processing.  run_recovery_sync defaults to recovery.STALE_MIN_AGE_MINUTES —
    keep it that way.
    """
    if os.getenv("AMBER_CANARY", "").lower() == "true":
        logger.info("Canary worker ready - skipping stale document recovery")
        return

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

    # Community processing locks are deliberately NOT cleared here.
    #
    # They are set with `SET NX EX 7200` (tasks.py: process_communities), so a
    # lock left behind by a crashed worker expires on its own within the 2h
    # safety TTL. Deleting them at boot was safe with a single worker and is not
    # with `replicas: 3` (docker-compose.yml): this signal fires per replica, and
    # a restarting replica would release the locks the other two are holding
    # right now, letting two workers run community detection and summarisation
    # for the same tenant concurrently and clobber each other's writes.
    #
    # ponytail: the cost is that after a crash a tenant's community refresh can
    # be blocked for up to the remaining TTL. If that latency ever matters,
    # narrow the lock value (it already stores the owning task id) and clear only
    # locks whose task is no longer active — do not go back to a blanket flush.
