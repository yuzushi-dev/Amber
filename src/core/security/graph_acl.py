

class GraphACL:
    """
    Helper for generating secure Cypher/Graph queries that enforce Access Control.
    """

    @staticmethod
    def security_pattern(
        tenant_id: str,
        allowed_doc_ids: list[str] | None = None,
        variable_name: str = "e"
    ) -> str:
        """
        Generates a MATCH/WHERE clause to ensure the entity is accessible.

        Strategy:
        1. Tenant Isolation: Always enforce tenant_id property on the node.
        2. Path-based Access: If allowed_doc_ids is provided, enforce existence of path
           from allowed documents to the entity.

        Args:
            tenant_id: The tenant ID (mandatory).
            allowed_doc_ids: List of document IDs the user can see. If None, assumes full tenant access (e.g. admin).
            variable_name: The variable name of the entity in the calling query (default 'e').

        Returns:
            Cypher string fragment.
        """
        if allowed_doc_ids is not None:
            # We strictly filter by path from allowed documents.
            # This is expensive but secure.
            # Pattern: (d:Document)-[]->(c:Chunk)-[]->(e:Entity)
            # We check EXISTS path

            # Note: passing large list of IDs might be inefficient.
            # Ideally we pass $allowed_doc_ids parameter.

            return f"""
            MATCH ({variable_name}:Entity {{tenant_id: $tenant_id}})
            WHERE EXISTS {{
                MATCH (d:Document)-[:HAS_CHUNK]->(:Chunk)-[:MENTIONS]->({variable_name})
                WHERE d.id IN $allowed_doc_ids AND d.tenant_id = $tenant_id
            }}
            """
        else:
            # Full Tenant Access
            return f"MATCH ({variable_name}:Entity {{tenant_id: $tenant_id}})"

    @staticmethod
    def inject_security_parameters(params: dict, tenant_id: str, allowed_doc_ids: list[str] | None = None):
        """Helper to inject security params into the parameters dict."""
        params["tenant_id"] = tenant_id
        if allowed_doc_ids is not None:
            params["allowed_doc_ids"] = allowed_doc_ids
        return params

graph_acl = GraphACL()
