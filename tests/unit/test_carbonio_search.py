from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.ingestion.infrastructure.connectors.carbonio import CarbonioConnector


@pytest.mark.asyncio
async def test_chat_search_query():
    # Setup
    connector = CarbonioConnector(host="https://mock.com")
    connector.auth_token = "mock_token"
    connector.email = "me@date.com"
    connector.user_id = "my_uuid"
    connector.cookies = {}

    # Get the tool function
    tool_def = connector._tool_get_chat_history()
    get_history_func = tool_def["func"]

    # Mock data for rooms and users
    rooms_data = [
        {"id": "room1", "members": [{"userId": "u1"}, {"userId": "me"}], "type": "one_to_one"}
    ]
    users_batch_response = [{"id": "u1", "name": "Luca Arcara"}]

    # Mock httpx
    mock_response_rooms = MagicMock()
    mock_response_rooms.status_code = 200
    mock_response_rooms.json.return_value = rooms_data

    mock_response_users = MagicMock()
    mock_response_users.status_code = 200
    mock_response_users.json.return_value = users_batch_response

    # Mock messages returned by XMPP
    mock_messages = [
        {"sender": "Luca", "content": "Hello there", "timestamp": "2025-01-01"},
        {
            "sender": "Luca",
            "content": "This contains the secret code amber_v2",
            "timestamp": "2025-01-02",
        },
        {"sender": "Me", "content": "Checking config", "timestamp": "2025-01-03"},
    ]

    # Mock XMPP client import and instance
    # The function imports: from src.core.ingestion.infrastructure.connectors.carbonio_xmpp import get_chat_history as xmpp_get_history
    # We must patch it in the target module if it were top level, but it is local import.
    # However, sys.modules patching works.

    with patch(
        "src.core.ingestion.infrastructure.connectors.carbonio_xmpp.get_chat_history"
    ) as mock_xmpp_get_history:

        async def side_effect(*args, **kwargs):
            query = kwargs.get("search_query")
            if query:
                return [m for m in mock_messages if query.lower() in m["content"].lower()]
            return mock_messages

        mock_xmpp_get_history.side_effect = side_effect

        # We also need to mock the IMPORT inside the function.
        # This is tricky with local imports. A better way is to mock 'sys.modules["src.core.ingestion.infrastructure.connectors.carbonio_xmpp"]'
        # OR just mock the function if we can reachable it.
        # But wait, we can just patch 'src.core.connectors.carbonio.get_chat_history' which is NOT the tool func.

        # Let's try patching the module where the tool is defined so the import returns our mock.
        with patch.dict(
            "sys.modules",
            {
                "src.core.ingestion.infrastructure.connectors.carbonio_xmpp": MagicMock(
                    get_chat_history=mock_xmpp_get_history
                )
            },
        ):
            # Mock httpx client
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client_cls.return_value.__aenter__.return_value = mock_client

                async def http_side_effect(url, params=None, **kwargs):
                    if "rooms" in url:
                        return mock_response_rooms
                    if "users" in url:
                        return mock_response_users
                    return MagicMock(status_code=404)

                mock_client.get.side_effect = http_side_effect

                # TEST 1: Search for "amber"
                result_amber = await get_history_func("Luca", search_query="amber")
                print(f"Result Amber: {result_amber}")
                assert "amber_v2" in result_amber
                assert "Hello there" not in result_amber
                assert "matching 'amber'" in result_amber

                # TEST 2: Search for "config"
                result_config = await get_history_func("Luca", search_query="config")
                print(f"Result Config: {result_config}")
                assert "Checking config" in result_config
                assert "amber_v2" not in result_config

                # TEST 3: No results
                result_none = await get_history_func("Luca", search_query="xylophone")
                assert "found no messages matching 'xylophone'" in result_none
