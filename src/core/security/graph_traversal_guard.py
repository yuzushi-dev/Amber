class GraphTraversalGuard:
    """
    Security component to enforce ACLs during graph traversals.
    Ensures that traversals do not reveal nodes that the user is not authorized to see.
    """

    @staticmethod
    def get_acl_fragment(node_alias: str, param_name: str = "allowed_doc_ids") -> str:
        """
        Returns a Cypher WHERE clause fragment to filter nodes by allowed document IDs.

        Args:
            node_alias: The variable name of the node in the Cypher query (e.g., 'c', 'neighbor').
            param_name: The name of the parameter containing the allowed document IDs.

        Returns:
            A string containing the WHERE clause fragment.
        """
        # We assume the node has a 'document_id' property.
        # If allowed_doc_ids is provided (not null in query), we enforce it.
        # In Cypher, we can use a CASE or conditional logic, but it's cleaner to
        # let the python code decide whether to include this clause based on input.
        # Here we generate the strict clause assuming the parameter will be passed.
        return f"{node_alias}.document_id IN ${param_name}"

    @staticmethod
    def get_exclusion_fragment(node_alias: str, param_name: str = "excluded_doc_ids") -> str:
        """
        Returns a Cypher WHERE clause fragment that excludes nodes belonging to
        a blocklist of document IDs (e.g. non-READY documents whose chunks are
        still indexed). This is the inverse of `get_acl_fragment`: a blocklist,
        not an allowlist, so it must not be conflated with ACL enforcement.

        Args:
            node_alias: The variable name of the node in the Cypher query (e.g., 'c', 'neighbor').
            param_name: The name of the parameter containing the excluded document IDs.

        Returns:
            A string containing the WHERE clause fragment.
        """
        return f"NOT {node_alias}.document_id IN ${param_name}"

    @staticmethod
    def filter_path_query(
        base_query: str, check_nodes: list[str], param_name: str = "allowed_doc_ids"
    ) -> str:
        """
        Injects ACL checks into a Cypher query.

        Appends a WHERE/AND clause that restricts the given node aliases to
        documents listed in the ``param_name`` parameter.  Callers must pass the
        corresponding list in their query params.

        For complex multi-match queries, prefer constructing the ACL clause
        explicitly with ``get_acl_fragment``.

        NOTE: This helper performs simple string injection and is not aware of
        existing WHERE clauses — use only when the base_query has no WHERE yet.
        Raises ValueError if check_nodes is empty (nothing to guard).
        """
        if not check_nodes:
            raise ValueError("filter_path_query: check_nodes must not be empty")

        fragments = " AND ".join(
            GraphTraversalGuard.get_acl_fragment(alias, param_name) for alias in check_nodes
        )
        return f"{base_query}\nWHERE {fragments}"
