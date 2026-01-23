"""
Graph Tools
===========

Tools for the agent to interact with the Neo4j Knowledge Graph.
"""

import logging
from typing import Any

from src.core.graph.domain.ports.graph_client import get_graph_client

logger = logging.getLogger(__name__)

async def query_graph(query: str, parameters: dict[str, Any] | None = None) -> str:
    """
    Execute a read-only Cypher query against the knowledge graph.
    
    Use this tool to find relationships between entities, explore the graph structure,
    or look up specific nodes.
    
    Args:
        query: The Cypher query string (e.g. "MATCH (n:Person) RETURN n LIMIT 5")
        parameters: Optional dictionary of query parameters.
        
    Returns:
        JSON string representation of the query results.
    """
    try:
        results = await get_graph_client().execute_read(query, parameters)
        
        if not results:
            return "No results found."
            
        # Format results for readability
        formatted = []
        for record in results:
            formatted.append(str(record))
            
        return "\n".join(formatted)
        
    except Exception as e:
        return f"Error executing graph query: {str(e)}"

# Tool definitions list for easy import
GRAPH_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_graph",
            "description": "Execute a Cypher query to search the Knowledge Graph (Neo4j). Use this to find entities and relationships.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The Cypher query to execute."
                    }
                },
                "required": ["query"]
            }
        }
    }
]
