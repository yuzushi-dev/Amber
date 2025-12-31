"""
Celery Application Configuration
================================

Configures Celery for background task processing.
"""

import os
import logging

from celery import Celery
from celery.signals import worker_process_init

logger = logging.getLogger(__name__)

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
    worker_concurrency=4,
    # Task execution settings
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Result settings
    result_expires=3600,  # 1 hour
    # Retry settings
    task_default_retry_delay=60,
    task_max_retries=3,
)

# Task routing (optional, can be configured later)
celery_app.conf.task_routes = {
    "src.workers.tasks.ingestion.*": {"queue": "ingestion"},
    "src.workers.tasks.extraction.*": {"queue": "extraction"},
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
        from src.core.providers.factory import init_providers
        
        # Initialize providers with API keys from settings
        init_providers(
            openai_api_key=settings.openai_api_key,
            anthropic_api_key=settings.anthropic_api_key,
        )
        logger.info("Worker process providers initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize worker providers: {e}")
        # Don't fail worker startup - some tasks may not need providers
