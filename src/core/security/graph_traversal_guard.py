from typing import List, Optional

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
    def filter_path_query(base_query: str, check_nodes: List[str], param_name: str = "allowed_doc_ids") -> str:
        """
        Injects ACL checks into a Cypher query.
        
        This is a simple helper. For complex queries, it is better to construct 
        the query with the checks explicitly.
        """
        pass # Not implemented for now, relying on manual query construction with `get_acl_fragment`.
