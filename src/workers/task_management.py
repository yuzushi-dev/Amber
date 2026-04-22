"""
Task Management Utilities
=========================

Utilities for managing and purging stale Celery tasks during configuration changes.
"""

import logging

from src.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def purge_community_tasks(tenant_id: str | None = None) -> int:
    """
    Revokes any active or reserved tasks related to community processing.

    Args:
        tenant_id: Optional tenant ID to filter tasks (not easily supported by Celery,
                  so we currently purge all community tasks if any config changes).

    Returns:
        int: Number of tasks revoked.
    """
    task_name = "src.workers.tasks.process_communities"
    revoked_count = 0

    try:
        # 1. Inspect active and reserved tasks
        i = celery_app.control.inspect()
        active = i.active() or {}
        reserved = i.reserved() or {}
        scheduled = i.scheduled() or {}

        tasks_to_revoke = set()

        for source in [active, reserved, scheduled]:
            for _worker, tasks in source.items():
                for task in tasks:
                    if task.get("name") != task_name:
                        continue
                    if tenant_id is not None:
                        # Only revoke tasks whose first positional arg matches
                        # the requesting tenant — prevent cross-tenant blast radius.
                        task_tenant = (task.get("args") or [None])[0]
                        if task_tenant != tenant_id:
                            continue
                    tasks_to_revoke.add(task.get("id"))

        tasks_to_revoke = list(tasks_to_revoke)

        if tasks_to_revoke:
            logger.info(f"Revoking {len(tasks_to_revoke)} stale {task_name} tasks...")
            celery_app.control.revoke(tasks_to_revoke, terminate=True, signal="SIGKILL")
            revoked_count = len(tasks_to_revoke)

        # 2. Purge from queue (Redis only)
        # This is harder to do selectively. We'll rely on revocation for now.

        return revoked_count

    except Exception as e:
        logger.error(f"Failed to purge community tasks: {e}")
        return 0


async def invalidate_and_retrigger_communities(tenant_id: str):
    """
    Marks all communities for a tenant as stale and triggers a fresh summarization task.
    """
    from src.amber_platform.composition_root import platform
    from src.workers.tasks import process_communities

    logger.info(f"Invalidating communities for tenant {tenant_id} due to config change...")

    try:
        # 1. Mark all processed communities as stale so they get re-summarized
        # We only mark 'ready' ones as stale. 'failed' ones will be retried anyway.
        query = """
        MATCH (c:Community {tenant_id: $tenant_id, status: 'ready'})
        SET c.is_stale = true, c.status = 'pending'
        RETURN count(c) as count
        """
        result = await platform.neo4j_client.execute_write(query, {"tenant_id": tenant_id})
        count = result[0]["count"] if result else 0

        logger.info(f"Marked {count} communities as stale for re-processing.")

        # 2. Trigger fresh task
        process_communities.delay(tenant_id)
        logger.info(f"Triggered fresh process_communities task for tenant {tenant_id}")

    except Exception as e:
        logger.error(f"Failed to invalidate/retrigger communities: {e}")
