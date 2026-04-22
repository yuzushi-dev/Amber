"""
Security tests for Task 9: community refresh per-tenant isolation.

Verifies that:
- purge_community_tasks(tenant_id) only revokes tasks for that tenant
- Tasks belonging to other tenants are NOT revoked (no cross-tenant blast)
- purge_community_tasks() with no tenant_id still purges all (global update path)
"""

from unittest.mock import MagicMock, patch


def _make_task(task_id, tenant_id):
    """Build a fake Celery task inspect entry."""
    return {
        "id": task_id,
        "name": "src.workers.tasks.process_communities",
        "args": [tenant_id],
        "kwargs": {},
    }


def test_purge_community_tasks_filters_by_tenant():
    """
    purge_community_tasks(tenant_id='tenant-a') must only revoke tasks whose
    first argument is 'tenant-a'.  Tasks for 'tenant-b' must NOT be revoked.
    """
    from src.workers.task_management import purge_community_tasks

    task_a = _make_task("task-001", "tenant-a")
    task_b = _make_task("task-002", "tenant-b")

    inspect_mock = MagicMock()
    inspect_mock.active.return_value = {"worker@host": [task_a, task_b]}
    inspect_mock.reserved.return_value = {}
    inspect_mock.scheduled.return_value = {}

    revoked_ids = []

    def fake_revoke(task_ids, terminate, signal):
        revoked_ids.extend(task_ids if isinstance(task_ids, list) else [task_ids])

    with patch("src.workers.task_management.celery_app") as mock_app:
        mock_app.control.inspect.return_value = inspect_mock
        mock_app.control.revoke.side_effect = fake_revoke

        count = purge_community_tasks(tenant_id="tenant-a")

    assert count == 1, (
        f"Expected 1 revoked task (tenant-a only), got {count}. "
        "Cross-tenant blast: other tenants' community tasks were cancelled."
    )
    assert "task-001" in revoked_ids, "tenant-a task must be revoked"
    assert "task-002" not in revoked_ids, (
        "tenant-b task was revoked even though only tenant-a config changed. "
        "Any tenant admin can disrupt community processing for all other tenants."
    )


def test_purge_community_tasks_no_tenant_purges_all():
    """
    purge_community_tasks() with no tenant_id (global config change path)
    must still revoke all matching tasks.
    """
    from src.workers.task_management import purge_community_tasks

    task_a = _make_task("task-001", "tenant-a")
    task_b = _make_task("task-002", "tenant-b")

    inspect_mock = MagicMock()
    inspect_mock.active.return_value = {"worker@host": [task_a, task_b]}
    inspect_mock.reserved.return_value = {}
    inspect_mock.scheduled.return_value = {}

    revoked_ids = []

    def fake_revoke(task_ids, terminate, signal):
        revoked_ids.extend(task_ids if isinstance(task_ids, list) else [task_ids])

    with patch("src.workers.task_management.celery_app") as mock_app:
        mock_app.control.inspect.return_value = inspect_mock
        mock_app.control.revoke.side_effect = fake_revoke

        count = purge_community_tasks(tenant_id=None)

    assert count == 2, f"Expected all 2 tasks revoked for global purge, got {count}"
    assert "task-001" in revoked_ids and "task-002" in revoked_ids


def test_config_update_passes_tenant_id_to_purge():
    """
    The update_tenant_config handler must pass tenant_id to purge_community_tasks()
    rather than calling it with no arguments.
    """
    import inspect

    import src.api.routes.admin.config as cfg_module
    source = inspect.getsource(cfg_module.update_tenant_config)
    # The fixed code should call purge_community_tasks(tenant_id=...) or
    # purge_community_tasks(tenant_id) — not the bare purge_community_tasks()
    assert "purge_community_tasks()" not in source, (
        "update_tenant_config calls purge_community_tasks() without tenant_id. "
        "A config update for one tenant revokes community tasks for ALL tenants."
    )
