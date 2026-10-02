

from src.core.security.graph_traversal_guard import GraphTraversalGuard


class TestGraphTraversalGuard:
    def test_get_acl_fragment(self):
        fragment = GraphTraversalGuard.get_acl_fragment("node", "params")
        assert fragment == "node.document_id IN $params"

        fragment = GraphTraversalGuard.get_acl_fragment("c", "allowed_list")
        assert fragment == "c.document_id IN $allowed_list"
