"""
Worker Orchestration Integration Test
======================================

Verifies the Celery task and API integration.
"""

from unittest.mock import MagicMock, patch

from src.workers.tasks import _publish_status, process_document


def test_publish_status():
    """Test status publishing to Redis."""
    with patch("redis.Redis") as mock_redis_class:
        mock_client = MagicMock()
        mock_redis_class.from_url.return_value = mock_client

        _publish_status("doc123", "EXTRACTING", 25)

        mock_redis_class.from_url.assert_called_once()
        mock_client.publish.assert_called_once()


def test_celery_task_registered():
    """Verify process_document task is properly registered."""
    from src.workers.celery_app import celery_app

    tasks = celery_app.tasks
    assert "src.workers.tasks.process_document" in tasks
    assert "src.workers.tasks.health_check" in tasks


def test_retry_configuration():
    """Verify retry configuration is set correctly."""
    task = process_document
    assert task.max_retries == 3
    assert task.default_retry_delay == 60


def test_publish_status_with_error():
    """Test status publishing includes error when provided."""
    import json

    with patch("redis.Redis") as mock_redis_class:
        mock_client = MagicMock()
        mock_redis_class.from_url.return_value = mock_client

        _publish_status("doc123", "FAILED", 100, error="Test error")

        call_args = mock_client.publish.call_args
        channel = call_args[0][0]
        message = json.loads(call_args[0][1])

        assert "doc123" in channel
        assert message["status"] == "FAILED"
        assert message["error"] == "Test error"
