
import asyncio
import sys
import time
from pathlib import Path

# Add src to path
sys.path.append(str(Path(__file__).parent.parent))

from src.api.config import settings
from src.core.services.generation import GenerationService
from src.core.services.retrieval import RetrievalConfig, RetrievalService

# Benchmark Questions
QUERIES = [
    {
        "type": "Ideal",
        "question": "What is the order of splitting in SemanticChunker?",
        "expected": "Header -> Code Block -> Paragraph -> Sentence"
    },
    {
        "type": "Ideal",
        "question": "How does IngestionService handle duplicate files?",
        "expected": "Checks SHA256 hash, returns existing document if found."
    },
    {
        "type": "Hard",
        "question": "Trace the full flow of process_document in IngestionService. What happens after extraction?",
        "expected": "Classify -> Select Strategy -> Chunk -> Embed -> Graph Sync -> Enrich -> Ready"
    },
    {
        "type": "Hard",
        "question": "Does the SemanticChunker specifically support C++ file syntax?",
        "expected": "No, it uses generic Markdown/Regex patterns."
    }
]

async def run_benchmark():
    print("Initializing Services...")

    # Configure Retrieval
    retrieval_config = RetrievalConfig(
        milvus_host=settings.db.milvus_host,
        milvus_port=settings.db.milvus_port,
        enable_reranking=True
    )

    retrieval_service = RetrievalService(
        openai_api_key=settings.openai_api_key,
        redis_url=settings.db.redis_url,
        config=retrieval_config
    )

    generation_service = GenerationService(
        openai_api_key=settings.openai_api_key
    )

    print("\n--- Starting Benchmark ---\n")

    results = []

    for item in QUERIES:
        q = item["question"]
        print(f"Question ({item['type']}): {q}")

        start_time = time.perf_counter()

        # 1. Retrieve
        retrieval_result = await retrieval_service.retrieve(
            query=q,
            tenant_id=settings.tenant_id,
            top_k=5
        )

        # 2. Generate
        gen_result = await generation_service.generate(
            query=q,
            candidates=retrieval_result.chunks
        )

        elapsed = (time.perf_counter() - start_time) * 1000

        print(f"Answer: {gen_result.answer[:150]}...")
        print(f"Time: {elapsed:.2f}ms")
        print("-" * 50)

        results.append({
            "question": q,
            "type": item["type"],
            "answer": gen_result.answer,
            "retrieved_chunks": [c["content"][:50] for c in retrieval_result.chunks],
            "latency_ms": elapsed
        })

    # Save detailed report
    with open("benchmark_results_baseline.md", "w") as f:
        f.write("# Benchmark Baseline (Linear RAG)\n\n")
        f.write("| Type | Question | Latency (ms) | Answer Quality |\n")
        f.write("| :--- | :--- | :--- | :--- |\n")

        for r in results:
            # Simple quality check (manual review needed really)
            f.write(f"| {r['type']} | {r['question']} | {r['latency_ms']:.1f} | {r['answer'].replace(chr(10), ' ')} |\n")

    print("\nBenchmark Complete. Results saved to benchmark_results_baseline.md")

if __name__ == "__main__":
    asyncio.run(run_benchmark())
