from unittest.mock import AsyncMock, patch, MagicMock
import pytest
from fastapi.testclient import TestClient
from src.api.main import app
from src.amber_platform.composition_root import platform
neo4j_client = platform.neo4j_client


# Mock Key Object
class MockKey:
    def __init__(self):
        self.name = "test_key"
        self.tenants = [MagicMock(id="test_tenant")]
        self.scopes = ["read", "write"]

@pytest.fixture
def client():
    # We need to permit the unauthenticated request OR mock the auth process.
    # Approach: Mock ApiKeyService.validate_key
    with patch("src.core.admin_ops.application.api_key_service.ApiKeyService.validate_key", new_callable=AsyncMock) as mock_validate:
        mock_validate.return_value = MockKey()
        with TestClient(app) as c:
            yield c

@pytest.fixture
def auth_headers():
    return {"X-API-Key": "dummy_key", "X-Tenant-ID": "test_tenant"}

def test_get_top_nodes(client, auth_headers):
    """Test GET /v1/graph/editor/top"""
    mock_data = [
        {"id": "NodeA", "label": "NodeA", "type": "Entity", "community_id": 1, "degree": 10},
        {"id": "NodeB", "label": "NodeB", "type": "Entity", "community_id": 2, "degree": 5}
    ]
    
    with patch.object(neo4j_client, 'execute_read', new_callable=AsyncMock) as mock_read:
        mock_read.return_value = mock_data
        
        response = client.get(
            "/v1/graph/editor/top?limit=5",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["id"] == "NodeA"

def test_search_nodes(client, auth_headers):
    """Test GET /v1/graph/editor/search"""
    mock_data = [
        {"id": "Alpha", "label": "Alpha", "type": "Entity", "community_id": 1}
    ]
    
    with patch.object(neo4j_client, 'execute_read', new_callable=AsyncMock) as mock_read:
        mock_read.return_value = mock_data
        
        response = client.get(
            "/v1/graph/editor/search?q=Alp",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "Alpha"

def test_get_neighborhood(client, auth_headers):
    """Test GET /v1/graph/editor/neighborhood via get_node_neighborhood_graph"""
    mock_rows = [
        {
            "c_id": "Center", "c_type": "Node", "c_comm": 1,
            "r_type": "LINKS", "source": "Center", "target": "Neighbor",
            "n_id": "Neighbor", "n_type": "Node", "n_comm": 1
        }
    ]
    
    with patch.object(neo4j_client, 'execute_read', new_callable=AsyncMock) as mock_read:
        mock_read.return_value = mock_rows
        
        response = client.get(
            "/v1/graph/editor/neighborhood?node_id=Center",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1
