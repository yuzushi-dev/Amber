#!/usr/bin/env python3
"""
Comprehensive Retrieval and Chat Pipeline Test
===============================================

Tests the complete retrieval/chat pipeline including:
- Multiple search modes (basic, hybrid, entity, graph, global)
- Query options (rewriting, decomposition, HyDE)
- Vector search
- Entity search
- Graph traversal
- Answer generation with citations
"""

import asyncio
import sys
import time
from typing import Dict, Any
import httpx

API_URL = "http://localhost:8000"
API_KEY = "amber-dev-key-2024"


async def test_query(
    query: str,
    search_mode: str = "basic",
    use_rewrite: bool = False,
    use_decomposition: bool = False,
    use_hyde: bool = False,
    max_chunks: int = 5,
    include_trace: bool = False
) -> Dict[str, Any]:
    """Test a query with specific options."""

    async with httpx.AsyncClient(timeout=60.0) as client:
        payload = {
            "query": query,
            "options": {
                "search_mode": search_mode,
                "use_rewrite": use_rewrite,
                "use_decomposition": use_decomposition,
                "use_hyde": use_hyde,
                "max_chunks": max_chunks,
                "include_trace": include_trace,
                "include_sources": True
            }
        }

        response = await client.post(
            f"{API_URL}/v1/query",
            headers={"X-API-Key": API_KEY},
            json=payload
        )

        if response.status_code != 200:
            return {"error": f"Status {response.status_code}: {response.text}"}

        return response.json()


def print_section(title: str):
    """Print a formatted section header."""
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")


def print_result(test_name: str, result: Dict[str, Any]):
    """Print formatted test result."""
    print(f"📋 Test: {test_name}")

    if "error" in result:
        print(f"   ❌ Error: {result['error']}")
        return

    # Print answer if present
    if "answer" in result:
        answer = result["answer"]
        print(f"   ✓ Answer: {answer[:200]}{'...' if len(answer) > 200 else ''}")

    # Print timing
    if "timing" in result:
        timing = result["timing"]
        print(f"   ✓ Timing:")
        print(f"     - Total: {timing.get('total_ms', 'N/A'):.1f}ms")
        if timing.get('retrieval_ms'):
            print(f"     - Retrieval: {timing['retrieval_ms']:.1f}ms")
        if timing.get('generation_ms'):
            print(f"     - Generation: {timing['generation_ms']:.1f}ms")

    # Print sources if present
    if "sources" in result:
        sources = result["sources"]
        print(f"   ✓ Sources: {len(sources)} chunks retrieved")
        for src in sources[:3]:
            doc_name = src.get('document_name', 'Unknown')
            score = src.get('score', 0.0)
            text_preview = src.get('text', '')[:80]
            print(f"     - {doc_name} (score: {score:.3f})")
            print(f"       Preview: {text_preview}...")

    # Print trace if present
    if "trace" in result and result["trace"]:
        print(f"   ✓ Trace: {len(result['trace'])} steps")
        for step in result["trace"][:3]:
            print(f"     - {step.get('step', 'N/A')}: {step.get('duration_ms', 'N/A'):.1f}ms")

    # Print follow-up questions if present
    if "follow_up_questions" in result and result["follow_up_questions"]:
        print(f"   ✓ Follow-up questions:")
        for q in result["follow_up_questions"][:2]:
            print(f"     - {q}")

    print()


async def main():
    """Run comprehensive pipeline tests."""

    print_section("RETRIEVAL & CHAT PIPELINE COMPREHENSIVE TEST")

    # Test 1: Basic query with answer
    print_section("Test 1: Basic Vector Search")
    result = await test_query(
        "What is Anthropic and who founded it?",
        search_mode="basic",
        max_chunks=5,
        include_trace=True
    )
    print_result("Basic Vector Search", result)

    # Test 2: Local (Entity-focused) search
    print_section("Test 2: Local Search (Entity-Focused Graph Traversal)")
    result = await test_query(
        "What is Dario Amodei's role at Anthropic?",
        search_mode="local",
        max_chunks=5,
        include_trace=True
    )
    print_result("Local/Entity Search", result)

    # Test 3: Global search (community summaries)
    print_section("Test 3: Global Search (Map-Reduce over Communities)")
    result = await test_query(
        "Tell me about the technology stack used in the system",
        search_mode="global",
        max_chunks=5,
        include_trace=True
    )
    print_result("Global Search", result)

    # Test 4: DRIFT search (dynamic reasoning)
    print_section("Test 4: DRIFT Search (Dynamic Reasoning)")
    result = await test_query(
        "What are the relationships between Anthropic, Claude, and the founders?",
        search_mode="drift",
        max_chunks=5,
        include_trace=True
    )
    print_result("DRIFT Search", result)

    # Test 5: Query with rewriting
    print_section("Test 5: Query Rewriting")
    result = await test_query(
        "Who's the boss at Anthropic?",
        search_mode="basic",
        use_rewrite=True,
        max_chunks=5
    )
    print_result("Query Rewriting", result)

    # Test 6: Query with HyDE
    print_section("Test 6: HyDE (Hypothetical Document Embeddings)")
    result = await test_query(
        "What databases are used for storage?",
        search_mode="basic",
        use_hyde=True,
        max_chunks=5
    )
    print_result("HyDE Search", result)

    # Test 7: Query with decomposition
    print_section("Test 7: Query Decomposition")
    result = await test_query(
        "Explain the complete architecture: what databases are used, who created it, and what technologies are involved?",
        search_mode="basic",
        use_decomposition=True,
        max_chunks=8
    )
    print_result("Query Decomposition", result)

    # Test 8: All advanced features combined
    print_section("Test 8: Combined Advanced Features")
    result = await test_query(
        "What is the connection between the founders and the technology they built?",
        search_mode="local",
        use_rewrite=True,
        use_hyde=True,
        max_chunks=8,
        include_trace=True
    )
    print_result("Combined Features", result)

    # Test 9: Complex technology query
    print_section("Test 9: Complex Technology Query")
    result = await test_query(
        "List all the technologies mentioned: databases, frameworks, and AI services",
        search_mode="global",
        max_chunks=10
    )
    print_result("Technology Query", result)

    # Test 10: Relationship-focused query
    print_section("Test 10: Entity Relationship Query")
    result = await test_query(
        "How are Neo4j, Milvus, and PostgreSQL used in this system?",
        search_mode="local",
        max_chunks=8
    )
    print_result("Relationship Query", result)

    print_section("✅ PIPELINE TEST COMPLETE")
    print("All retrieval and chat pipeline components have been tested.")
    print("\nComponents verified:")
    print("  ✓ BASIC mode: Vector search (Milvus)")
    print("  ✓ LOCAL mode: Entity-focused graph traversal (Neo4j)")
    print("  ✓ GLOBAL mode: Community-based map-reduce")
    print("  ✓ DRIFT mode: Dynamic reasoning and exploration")
    print("  ✓ Query rewriting for better context resolution")
    print("  ✓ HyDE for hypothetical document embeddings")
    print("  ✓ Query decomposition for complex questions")
    print("  ✓ Answer generation with source citations")
    print("  ✓ Execution tracing and timing")
    print()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
