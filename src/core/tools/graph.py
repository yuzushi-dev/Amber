"""
Graph Tools
===========

Tools for the agent to interact with the Neo4j Knowledge Graph.
"""

import re
from typing import Any

# ---------------------------------------------------------------------------
# Write-clause detection (case-insensitive, word-boundary)
# ---------------------------------------------------------------------------
_WRITE_CLAUSE_RE = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH\s+DELETE|SET|REMOVE|LOAD\s+CSV|CALL\s*\{|apoc\.)\b",
    re.IGNORECASE,
)


def _contains_write_clause(query: str) -> bool:
    """Return True if the Cypher query contains any write (mutating) clause."""
    return bool(_WRITE_CLAUSE_RE.search(query))


def _references_tenant_id(query: str, parameters: dict[str, Any] | None) -> bool:
    """
    Return True when:
      - the query text references the $tenant_id parameter, AND
      - the parameters dict supplies a 'tenant_id' key bound from trusted context.

    This ensures the LLM-authored query cannot omit the tenant predicate.
    """
    # Must reference the Cypher parameter in the query text
    if "$tenant_id" not in query:
        return False
    # The trusted parameters dict (injected by the factory, not by the LLM) must
    # contain the real tenant_id value.
    return bool(parameters and "tenant_id" in parameters)


# ---------------------------------------------------------------------------
# Factory — call this with the trusted tenant_id from the request context
# ---------------------------------------------------------------------------

def create_graph_tool(tenant_id: str) -> dict[str, Any]:
    """
    Build a tenant-scoped ``query_graph`` tool with a source-provenance gate.

    The returned dict has two keys:
      - ``"func"`` — the async callable the agent executor will invoke
      - ``"schema"`` — the OpenAI-style function schema for the LLM

    Security properties
    -------------------
    1. **Read-only**: any Cypher containing write clauses (CREATE, MERGE, DELETE,
       SET, REMOVE, DETACH DELETE, LOAD CSV, CALL{...}, apoc.*) is rejected before
       execution.
    2. **Tenant scoping**: the query MUST reference ``$tenant_id`` as a Cypher
       parameter.  The factory binds its value from the trusted request context
       (``tenant_id`` argument), NOT from anything the LLM supplies.  If the query
       omits ``$tenant_id``, it is rejected.

    Limitation
    ----------
    The guard is a *require-and-bind* approach rather than a full Cypher AST rewrite.
    It forces the LLM-generated query to include ``$tenant_id`` predicates and then
    overrides the bound value with the real tenant.  A sufficiently adversarial query
    could still filter by ``$tenant_id`` while leaking data through other means (e.g.
    cross-tenant relationship traversals that only *start* from a scoped node).  A
    full AST-level rewrite would close that gap but is outside this surgical patch.
    """

    async def query_graph(query: str, parameters: dict[str, Any] | None = None) -> str:
        """
        Validate Cypher and fail closed until commercial source provenance is available.

        The query MUST reference the ``$tenant_id`` parameter so results are
        limited to the caller's tenant.  Write clauses are not permitted.

        Args:
            query: The Cypher query string.  Must include ``$tenant_id`` (e.g.
                   ``MATCH (n:Entity {tenant_id: $tenant_id}) RETURN n LIMIT 5``).
            parameters: Optional extra query parameters (must not override
                        ``tenant_id`` — it is always bound from server context).

        Returns:
            JSON string representation of the query results, or an error message.
        """
        # --- 1. Read-only enforcement ---
        if _contains_write_clause(query):
            return (
                "Error: write operations (CREATE, MERGE, DELETE, SET, REMOVE, "
                "DETACH DELETE, LOAD CSV, CALL{...}, apoc.*) are not permitted in "
                "the graph tool.  Only read-only Cypher is allowed."
            )

        # --- 2. Merge caller-supplied parameters, then bind tenant_id from trusted context ---
        merged_params: dict[str, Any] = dict(parameters) if parameters else {}
        # Always overwrite with the trusted value — the LLM cannot influence this.
        merged_params["tenant_id"] = tenant_id

        # --- 3. Tenant-scoping enforcement ---
        if not _references_tenant_id(query, merged_params):
            return (
                "Error: the query must reference the $tenant_id parameter to ensure "
                "results are scoped to your tenant.  Include a predicate such as "
                "``{tenant_id: $tenant_id}`` or ``WHERE n.tenant_id = $tenant_id``."
            )

        # Free-form Cypher cannot prove the edition provenance of returned aggregates.
        return (
            "Graph lookup unavailable: commercial source provenance cannot be verified. "
            "Use search_codebase to retrieve permitted documents."
        )

    schema = {
        "type": "function",
        "function": {
            "name": "query_graph",
            "description": (
                "Execute a read-only Cypher query to search the Knowledge Graph (Neo4j). "
                "The query MUST include a $tenant_id predicate (e.g. "
                "{tenant_id: $tenant_id}) to scope results to the current tenant. "
                "Write operations are not allowed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "The Cypher query to execute.  Must reference $tenant_id. "
                            "Example: MATCH (n:Entity {tenant_id: $tenant_id}) "
                            "RETURN n LIMIT 5"
                        ),
                    },
                    "parameters": {
                        "type": "object",
                        "description": (
                            "Optional extra Cypher parameters (do not supply tenant_id "
                            "— it is bound automatically from the server context)."
                        ),
                    },
                },
                "required": ["query"],
            },
        },
    }

    return {"func": query_graph, "schema": schema}
