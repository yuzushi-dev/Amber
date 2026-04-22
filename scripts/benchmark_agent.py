
import asyncio
import sys
import time
from pathlib import Path

# Add src to path
sys.path.append(str(Path(__file__).parent.parent))

from src.api.config import settings
from src.api.routes.query import query as query_endpoint
from src.api.schemas.query import QueryOptions, QueryRequest


# Mock Request
class MockRequest:
    def __init__(self, tenant_id="default"):
        self.state = type('obj', (object,), {'tenant_id': tenant_id})

# Benchmark Questions
QUERIES = [
    {
        "type": "Ideal",
        "question": "What is the order of splitting in SemanticChunker?",
        "expected": "Header -> Code Block -> Paragraph -> Sentence"
    },
    {
        "type": "Hard",
        "question": "Trace the full flow of process_document in IngestionService. What happens after extraction?",
        "expected": "Classify -> Select Strategy -> Chunk -> Embed -> Graph Sync -> Enrich -> Ready"
    }
]

async def run_benchmark():
    print("Initializing Services for Agent Benchmark...")

    # We can invoke the endpoint function directly to test the integration
    # Ideally we should spin up the server, but direct invocation is faster for testing logic.

    print("\n--- Starting Agent Benchmark ---\n")

    results = []

    for item in QUERIES:
        q = item["question"]
        print(f"Question ({item['type']}): {q}")

        start_time = time.perf_counter()

        request = QueryRequest(
            query=q,
            options=QueryOptions(agent_mode=True) # ENABLE AGENT MODE
        )
        http_request = MockRequest(settings.tenant_id)

        try:
            response = await query_endpoint(request, http_request)

            elapsed = (time.perf_counter() - start_time) * 1000

            print(f"Answer: {response.answer[:150]}...")
            print(f"Time: {elapsed:.2f}ms")

            # Print Trace steps if any
            if response.trace:
                for t in response.trace:
                    print(f"  -> {t.step}")
                    if "tool_call" in t.step:
                         print(f"     Args: {t.details.get('args', '')}")
                         print(f"     Output: {t.details.get('output', '')[:100]}...")

        except Exception as e:
            print(f"Error: {e}")
            response = None
            elapsed = 0

        print("-" * 50)

        results.append({
            "question": q,
            "type": item["type"],
            "answer": response.answer if response else "Error",
            "latency_ms": elapsed
        })

    # Save detailed report
    with open("benchmark_results_agent.md", "w") as f:
        f.write("# Benchmark Results (Agent Phase 1)\n\n")
        f.write("| Type | Question | Latency (ms) | Answer Quality |\n")
        f.write("| :--- | :--- | :--- | :--- |\n")

        for r in results:
            f.write(f"| {r['type']} | {r['question']} | {r['latency_ms']:.1f} | {r['answer'].replace(chr(10), ' ')} |\n")

    print("\nBenchmark Complete. Results saved to benchmark_results_agent.md")

if __name__ == "__main__":
    asyncio.run(run_benchmark())
