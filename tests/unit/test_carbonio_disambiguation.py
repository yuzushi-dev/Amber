from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.ingestion.infrastructure.connectors.carbonio import CarbonioConnector


@pytest.mark.asyncio
async def test_chat_disambiguation():
    # Setup
    connector = CarbonioConnector(host="https://mock.com")
    connector.auth_token = "mock_token"
    connector.email = "me@date.com"
    connector.user_id = "my_uuid"

    # Get the tool function
    tool_def = connector._tool_get_chat_history()
    get_history_func = tool_def["func"]

    # Mock data
    rooms_data = [
        {"id": "room1", "members": [{"userId": "u1"}, {"userId": "me"}], "type": "one_to_one"},
        {"id": "room2", "members": [{"userId": "u2"}, {"userId": "me"}], "type": "one_to_one"},
    ]

    users_batch_response = [
        {"id": "u1", "name": "Luca Arcara"},
        {"id": "u2", "name": "Luca Piccoli"},
    ]

    # Mock httpx
    mock_response_rooms = MagicMock()
    mock_response_rooms.status_code = 200
    mock_response_rooms.json.return_value = rooms_data

    mock_response_users = MagicMock()
    mock_response_users.status_code = 200
    mock_response_users.json.return_value = users_batch_response

    # We need to mock httpx.AsyncClient context manager
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        # Setup side effects for get requests
        async def side_effect(url, params=None, **kwargs):
            if "rooms" in url:
                return mock_response_rooms
            if "users" in url:
                return mock_response_users
            return MagicMock(status_code=404)

        mock_client.get.side_effect = side_effect

        # Execute Query "Luca"
        result = await get_history_func("Luca")

        # Verify
        print(f"Result: {result}")
        assert "multiple people matching 'Luca'" in result
        assert "Luca Arcara" in result
        assert "Luca Piccoli" in result

        # Execute Query "Luca Arcara" (Specific)
        # Should proceed to XMPP (which we should also mock or expect fallback)
        # Since we didn't mock XMPP import, it might fail or hit ImportError catch

        # To test success path, we can try but the ambiguity test is the main goal here.
