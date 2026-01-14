import pytest
from unittest.mock import AsyncMock, MagicMock
from src.api.routes.admin.feedback import export_golden_dataset
from src.core.models.feedback import Feedback

@pytest.mark.asyncio
async def test_export_golden_dataset():
    """Test that the export endpoint streams valid JSONL for verified items."""
    
    # Mock Database Session
    mock_db = AsyncMock()
    mock_result = MagicMock()
    
    # Create fake "Verified" feedback
    fake_feedbacks = [
        Feedback(
            id="1", 
            request_id="req1", 
            score=1.0, 
            golden_status="VERIFIED", 
            comment="Great answer", 
            metadata_json={"query": "Q1", "answer": "A1"}
        ),
        Feedback(
            id="2", 
            request_id="req2", 
            score=1.0, 
            golden_status="VERIFIED", 
            comment="Perfect", 
            metadata_json={"query": "Q2", "answer": "A2"}
        )
    ]
    
    mock_result.scalars.return_value.all.return_value = fake_feedbacks
    mock_db.execute.return_value = mock_result

    # Call Endpoint
    response = await export_golden_dataset(format="jsonl", db=mock_db)
    
    assert response.headers["content-type"] == "application/x-jsonlines"
    
    # Collect streamed content
    content = ""
    async for chunk in response.body_iterator:
        content += chunk
        
    lines = content.strip().split("\n")
    assert len(lines) == 2
    
    import json
    record1 = json.loads(lines[0])
    assert record1["id"] == "1"
    assert record1["metadata"]["query"] == "Q1"
