"""
Task Management Unit Tests
==========================

Tests for stale task cleanup and community invalidation utilities.
"""

from unittest.mock import MagicMock, patch, AsyncMock
import pytest
from src.workers.task_management import purge_community_tasks, invalidate_and_retrigger_communities

@pytest.fixture
def mock_celery_control():
    with patch("src.workers.celery_app.celery_app.control") as mock:
        yield mock

@pytest.fixture
def mock_platform():
    with patch("src.amber_platform.composition_root.platform") as mock:
        mock.neo4j_client = AsyncMock()
        mock.neo4j_client.execute_write.return_value = [{"count": 5}]
        yield mock

@pytest.fixture
def mock_process_communities():
    with patch("src.workers.tasks.process_communities") as mock:
        yield mock

def test_purge_community_tasks_success(mock_celery_control):
    # Setup inspection results
    inspect_mock = MagicMock()
    mock_celery_control.inspect.return_value = inspect_mock
    
    task_name = "src.workers.tasks.process_communities"
    target_id1 = "task-123"
    target_id2 = "task-456"
    
    # Active tasks
    inspect_mock.active.return_value = {
        "worker1": [{"id": target_id1, "name": task_name}],
        "worker2": [{"id": "other-task", "name": "other.task"}]
    }
    # Reserved tasks
    inspect_mock.reserved.return_value = {
        "worker1": [{"id": target_id2, "name": task_name}]
    }
    # Scheduled tasks
    inspect_mock.scheduled.return_value = {}

    # Execute
    count = purge_community_tasks()

    # Verify
    assert count == 2
    mock_celery_control.revoke.assert_called_once()
    
    # Check updated call args structure for recent celestial versions or mock behavior
    call_args = mock_celery_control.revoke.call_args
    revoked_ids = call_args[0][0]
    kwargs = call_args[1]
    
    assert set(revoked_ids) == {target_id1, target_id2}
    assert kwargs.get("terminate") is True
    assert kwargs.get("signal") == "SIGKILL"

def test_purge_community_tasks_no_tasks(mock_celery_control):
    inspect_mock = MagicMock()
    mock_celery_control.inspect.return_value = inspect_mock
    inspect_mock.active.return_value = None
    inspect_mock.reserved.return_value = {}
    inspect_mock.scheduled.return_value = {}

    count = purge_community_tasks()

    assert count == 0
    mock_celery_control.revoke.assert_not_called()

def test_purge_community_tasks_error_handling(mock_celery_control):
    mock_celery_control.inspect.side_effect = Exception("Celery connection failed")
    
    count = purge_community_tasks()
    
    assert count == 0
    # Should not raise exception

@pytest.mark.asyncio
async def test_invalidate_and_retrigger_communities_success(mock_platform, mock_process_communities):
    tenant_id = "tenant-001"
    
    await invalidate_and_retrigger_communities(tenant_id)
    
    # Verify Neo4j update
    mock_platform.neo4j_client.execute_write.assert_called_once()
    query = mock_platform.neo4j_client.execute_write.call_args[0][0]
    params = mock_platform.neo4j_client.execute_write.call_args[0][1]
    
    assert "SET c.is_stale = true" in query
    assert "status: 'ready'" in query
    assert params["tenant_id"] == tenant_id
    
    # Verify task trigger
    mock_process_communities.delay.assert_called_once_with(tenant_id)

@pytest.mark.asyncio
async def test_invalidate_and_retrigger_communities_failure(mock_platform, mock_process_communities):
    mock_platform.neo4j_client.execute_write.side_effect = Exception("DB Error")
    
    await invalidate_and_retrigger_communities("tenant-001")
    
    # Should handle error gracefully and log it (we can't assert logging easily without caplog, but it shouldn't raise)
    mock_process_communities.delay.assert_not_called()
