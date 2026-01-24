from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.retrieval.application.search.graph import GraphSearcher
from src.core.security.graph_traversal_guard import GraphTraversalGuard


class TestGraphTraversalGuard:
    def test_get_acl_fragment(self):
        fragment = GraphTraversalGuard.get_acl_fragment("node", "params")
        assert fragment == "node.document_id IN $params"

        fragment = GraphTraversalGuard.get_acl_fragment("c", "allowed_list")
        assert fragment == "c.document_id IN $allowed_list"

@pytest.mark.asyncio
class TestGraphSearcherSecurity:
    async def test_search_by_entities_with_acls(self):
        mock_neo4j = MagicMock()
        mock_neo4j.execute_read = AsyncMock(return_value=[])

        searcher = GraphSearcher(mock_neo4j)

        entity_ids = ["e1", "e2"]
        tenant_id = "tenant1"
        allowed_doc_ids = ["doc1", "doc2"]

        await searcher.search_by_entities(entity_ids, tenant_id, allowed_doc_ids=allowed_doc_ids)

        # Verify query contains ACL clause
        call_args = mock_neo4j.execute_read.call_args
        query = call_args[0][0]
        params = call_args[0][1]

        assert "c.document_id IN $allowed_doc_ids" in query
        assert params["allowed_doc_ids"] == allowed_doc_ids
        assert params["entity_ids"] == entity_ids

    async def test_search_by_entities_without_acls(self):
        mock_neo4j = MagicMock()
        mock_neo4j.execute_read = AsyncMock(return_value=[])

        searcher = GraphSearcher(mock_neo4j)

        await searcher.search_by_entities(["e1"], "tenant1", allowed_doc_ids=None)

        call_args = mock_neo4j.execute_read.call_args
        query = call_args[0][0]
        params = call_args[0][1]

        assert "c.document_id IN $allowed_doc_ids" not in query
        assert "allowed_doc_ids" not in params

    async def test_search_by_neighbors_with_acls(self):
        mock_neo4j = MagicMock()
        mock_neo4j.execute_read = AsyncMock(return_value=[])

        searcher = GraphSearcher(mock_neo4j)

        chunk_ids = ["c1"]
        tenant_id = "tenant1"
        allowed_doc_ids = ["doc1"]

        await searcher.search_by_neighbors(chunk_ids, tenant_id, allowed_doc_ids=allowed_doc_ids)

        call_args = mock_neo4j.execute_read.call_args
        query = call_args[0][0]
        params = call_args[0][1]

        assert "neighbor.document_id IN $allowed_doc_ids" in query
        assert params["allowed_doc_ids"] == allowed_doc_ids
