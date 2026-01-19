
import pytest
import uuid
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport
from src.api.main import app

@pytest.fixture
async def async_client():
    """Create async test client."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

@pytest.fixture
def mock_deps():
    """Mock external dependencies to avoid side effects."""
    with patch("src.api.routes.admin.feedback.TuningService") as mock_admin_tuning, \
         patch("src.api.routes.admin.feedback.context_graph_writer") as mock_admin_graph, \
         patch("src.api.routes.admin.feedback.EmbeddingService") as mock_embedding:
        
        # Setup mocks
        mock_embedding.return_value.embed_text.return_value = [0.1] * 1536
        
        # Ensure async methods are awaitable
        mock_admin_tuning.return_value.analyze_feedback_for_tuning = AsyncMock()
        mock_admin_graph.log_feedback = AsyncMock()
        
        yield {
            "admin_tuning": mock_admin_tuning,
            "admin_graph": mock_admin_graph
        }

@pytest.mark.asyncio
class TestFeedbackWorkflow:
    """Integration tests for the Feedback Workflow."""

    async def test_feedback_workflow_full(self, async_client, api_key, mock_deps):
        """
        Verify the full feedback lifecycle in one flow to ensure ordering.
        1. Submit Positive Feedback (PENDING)
        2. Verify Positive Feedback (VERIFIED, ACTIVE)
        3. Submit Negative Feedback (PENDING)
        4. Verify Negative Feedback (VERIFIED, INACTIVE)
        5. Submit Mixed Feedback (PENDING)
        6. Reject Mixed Feedback (REJECTED)
        """
        
        # --- 1. Submit Positive Feedback ---
        request_id_pos = str(uuid.uuid4())
        response = await async_client.post(
            "/v1/feedback/",
            json={
                "request_id": request_id_pos,
                "is_positive": True,
                "comment": "Nice work",
                "metadata": {"session_id": "test_session_1"}
            },
            headers={"X-API-Key": api_key}
        )
        assert response.status_code == 200
        feedback_id_pos = response.json()["data"]["id"]
        
        # Check Pending
        pending_response = await async_client.get("/v1/admin/feedback/pending", headers={"X-API-Key": api_key})
        assert pending_response.status_code == 200
        assert any(f["id"] == feedback_id_pos for f in pending_response.json().get("data", []))
        
        # Ensure no side effects yet
        mock_deps["admin_tuning"].analyze_feedback_for_tuning.assert_not_called()
        mock_deps["admin_graph"].log_feedback.assert_not_called()
        
        # --- 2. Verify Positive Feedback ---
        verify_resp = await async_client.post(
            f"/v1/admin/feedback/{feedback_id_pos}/verify",
            headers={"X-API-Key": api_key}
        )
        assert verify_resp.status_code == 200
        
        # Check Side Effects for Positive
        mock_deps["admin_tuning"].return_value.analyze_feedback_for_tuning.assert_called_once()
        mock_deps["admin_graph"].log_feedback.assert_called_once()
        
        # Reset mocks
        mock_deps["admin_tuning"].return_value.analyze_feedback_for_tuning.reset_mock()
        mock_deps["admin_graph"].log_feedback.reset_mock()
        
        # --- 3. Submit Negative Feedback ---
        request_id_neg = str(uuid.uuid4())
        response = await async_client.post(
            "/v1/feedback/",
            json={
                "request_id": request_id_neg,
                "is_positive": False,
                "comment": "Bad result",
                "metadata": {"session_id": "test_session_2"}
            },
            headers={"X-API-Key": api_key}
        )
        assert response.status_code == 200
        feedback_id_neg = response.json()["data"]["id"]
        
        # --- 4. Verify Negative Feedback ---
        verify_resp = await async_client.post(
            f"/v1/admin/feedback/{feedback_id_neg}/verify",
            headers={"X-API-Key": api_key}
        )
        assert verify_resp.status_code == 200
        
        # Check Side Effects for Negative (Should still happen)
        mock_deps["admin_tuning"].return_value.analyze_feedback_for_tuning.assert_called_once()
        mock_deps["admin_graph"].log_feedback.assert_called_once()
        mock_deps["admin_tuning"].return_value.analyze_feedback_for_tuning.reset_mock()
        mock_deps["admin_graph"].log_feedback.reset_mock()
        
        # Check Approved List Status
        approved_resp = await async_client.get("/v1/admin/feedback/approved", headers={"X-API-Key": api_key})
        approved_list = approved_resp.json().get("data", [])
        
        pos_item = next((f for f in approved_list if f["id"] == feedback_id_pos), None)
        neg_item = next((f for f in approved_list if f["id"] == feedback_id_neg), None)
        
        assert pos_item is not None
        assert pos_item["is_active"] is True
        
        assert neg_item is not None
        assert neg_item["is_active"] is False
        
        # --- 5 & 6. Reject Feedback ---
        request_id_rej = str(uuid.uuid4())
        response = await async_client.post(
            "/v1/feedback/",
            json={
                "request_id": request_id_rej,
                "is_positive": True,
                "comment": "Meh",
                "metadata": {"session_id": "test_session_3"}
            },
            headers={"X-API-Key": api_key}
        )
        feedback_id_rej = response.json()["data"]["id"]
        
        reject_resp = await async_client.post(
            f"/v1/admin/feedback/{feedback_id_rej}/reject",
            headers={"X-API-Key": api_key}
        )
        assert reject_resp.status_code == 200
        
        # Ensure NO side effects
        mock_deps["admin_tuning"].return_value.analyze_feedback_for_tuning.assert_not_called()
        mock_deps["admin_graph"].log_feedback.assert_not_called()
        
        # Ensure not in Lists
        pending = await async_client.get("/v1/admin/feedback/pending", headers={"X-API-Key": api_key})
        approved = await async_client.get("/v1/admin/feedback/approved", headers={"X-API-Key": api_key})
        
        assert not any(f["id"] == feedback_id_rej for f in pending.json()["data"])
        assert not any(f["id"] == feedback_id_rej for f in approved.json()["data"])
        
        # --- CLEANUP ---
        # Clean up created data to prevent polluting the dev DB
        from src.api.deps import _async_session_maker
        from src.core.models.feedback import Feedback
        from src.core.models.memory import ConversationSummary
        from sqlalchemy import delete
        
        async with _async_session_maker() as session:
            # Delete Feedbacks
            await session.execute(
                delete(Feedback).where(Feedback.id.in_([feedback_id_pos, feedback_id_neg, feedback_id_rej]))
            )
            # Delete Conversation Summaries (if created, see below)
            await session.execute(
                delete(ConversationSummary).where(ConversationSummary.id.in_(["test_session_1", "test_session_2", "test_session_3"]))
            )
            await session.commit()

    @pytest.fixture(autouse=True)
    async def setup_conversation_data(self):
        """Create ConversationSummary data for the tests."""
        from src.api.deps import _async_session_maker
        from src.core.models.memory import ConversationSummary
        
        async with _async_session_maker() as session:
            # Create summaries used by the test
            summaries = [
                ConversationSummary(
                    id="test_session_1",
                    tenant_id="default",
                    user_id="test_user",
                    title="Test Session 1",
                    summary="Summary 1",
                    metadata_={"query": "Test Query 1", "answer": "Test Answer 1"}
                ),
                ConversationSummary(
                    id="test_session_2",
                    tenant_id="default",
                    user_id="test_user",
                    title="Test Session 2",
                    summary="Summary 2",
                    metadata_={"query": "Test Query 2", "answer": "Test Answer 2"}
                ),
                ConversationSummary(
                    id="test_session_3",
                    tenant_id="default",
                    user_id="test_user",
                    title="Test Session 3",
                    summary="Summary 3",
                    metadata_={"query": "Test Query 3", "answer": "Test Answer 3"}
                )
            ]
            
            for s in summaries:
                # Upsert or ignore if exists? Better to merge.
                await session.merge(s)
            
            await session.commit()

