"""
Retrieval Tools
===============

Tools that allow the Agent to access the Vector Knowledge Base.
"""

from typing import Any

from src.core.retrieval.application.retrieval_service import RetrievalService


def create_retrieval_tool(
    service: RetrievalService, tenant_id: str, query_scopes: Any | None = None
) -> dict[str, Any]:
    """
    Create the 'search_codebase' tool definition and callable.

    ``query_scopes`` carries the caller's authenticated group ACL so the agent's
    searches are scoped exactly like normal RAG; without it retrieval falls back
    to open scopes and the agent could surface documents outside the user's
    groups on a group-enforced tenant.
    """

    async def search_codebase(query: str) -> str:
        """Search the codebase using vector search."""
        result = await service.retrieve(
            query=query, tenant_id=tenant_id, top_k=5, query_scopes=query_scopes
        )

        if not result.chunks:
            return "No relevant code chunks found independent of the file system. Suggestion: Use 'list_directory' to look for files manually."

        # Format for the agent
        output = []
        for i, chunk in enumerate(result.chunks, 1):
            if isinstance(chunk, dict):
                meta = chunk.get("metadata") or {}
                content = chunk.get("content", "")
            else:
                meta = chunk.metadata or {}
                content = chunk.content

            source = meta.get("document_title", "unknown")
            content = content.strip()
            output.append(f"--- Result {i} (File: {source}) ---\n{content}\n")

        return "\n".join(output)

    schema = {
        "type": "function",
        "function": {
            "name": "search_codebase",
            "description": "Search the codebase for code snippets or documentation using semantic vector search.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query (e.g. 'how does authentication work', 'IngestionService class definition')",
                    }
                },
                "required": ["query"],
            },
        },
    }

    return {"name": "search_codebase", "func": search_codebase, "schema": schema}
