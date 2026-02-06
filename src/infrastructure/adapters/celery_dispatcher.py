"""
Celery Task Dispatcher
======================

Implementation of TaskDispatcher using Celery.
"""

import logging
from typing import Any

from src.core.ingestion.domain.ports.dispatcher import TaskDispatcher
from src.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


class CeleryTaskDispatcher(TaskDispatcher):
    """
    Dispatches tasks to the Celery worker queue.
    """

    async def dispatch(
        self, task_name: str, args: list[Any] | None = None, kwargs: dict[str, Any] | None = None
    ) -> str:
        args = args or []
        kwargs = kwargs or {}

        try:
            # We assume task_name matches the registered Celery task name string
            # OR we can map specific domain names to celery function names here if we want strict decoupling.
            # For simplicity, we assume strict naming.

            # Note: Celery send_task is synchronous unless we use its async API (rarely used).
            # Usually send_task is fast enough (push to Redis).
            # Check for eager execution
            if celery_app.conf.task_always_eager:
                if task_name in celery_app.tasks:
                    task = celery_app.tasks[task_name]
                    result = task.apply(args=args, kwargs=kwargs)
                    return str(result.id)
                else:
                    logger.warning(
                        f"Task {task_name} not found in registry for eager execution. Falling back to send_task."
                    )

            result = celery_app.send_task(task_name, args=args, kwargs=kwargs)
            return str(result.id)
        except Exception as e:
            logger.error(f"Failed to dispatch task {task_name}: {e}")
            raise RuntimeError(f"Task dispatch failed: {e}") from e

    async def cancel_task(self, task_id: str, terminate: bool = False) -> None:
        try:
            signal = "SIGTERM" if terminate else None
            celery_app.control.revoke(task_id, terminate=terminate, signal=signal)
        except Exception as e:
            logger.error(f"Failed to cancel task {task_id}: {e}")
