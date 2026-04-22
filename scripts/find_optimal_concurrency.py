import asyncio
import logging
import os
import sys
import time

# Ensure custom packages are loadable
if "/app/.packages" not in sys.path:
    sys.path.insert(0, "/app/.packages")

# Override to localhost since host.docker.internal is not resolving
os.environ["OLLAMA_BASE_URL"] = "http://localhost:11434/v1"

from src.amber_platform.composition_root import configure_settings, platform
from src.api.config import settings
from src.core.generation.infrastructure.providers.factory import ProviderFactory
from src.core.graph.application.communities.summarizer import CommunitySummarizer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def benchmark():
    configure_settings(settings)

    print(f"DEBUG: settings.default_llm_provider = {settings.default_llm_provider}")
    print(f"DEBUG: settings.ollama_base_url = {settings.ollama_base_url}")
    print(f"DEBUG: settings.openai_api_key = {settings.openai_api_key[:5]}...")

    tenant_id = "default"  # Assuming default tenant

    # 1. Fetch some communities to test with
    logger.info("Fetching candidate communities...")
    query = """
    MATCH (c:Community)
    RETURN c.id as id
    LIMIT 50
    """
    results = await platform.neo4j_client.execute_read(query)

    if not results:
        logger.error("No communities found to benchmark! Please run community detection first.")
        return

    all_ids = [r["id"] for r in results]
    logger.info(f"Found {len(all_ids)} communities available for benchmarking.")

    # We will test on a subset, e.g. 10 communities per run to save time/cost
    TEST_SIZE = 10
    subset_ids = all_ids[:TEST_SIZE]

    # Setup Factory
    factory = ProviderFactory(
        openai_api_key=settings.openai_api_key,
        anthropic_api_key=settings.anthropic_api_key,
        ollama_base_url=settings.ollama_base_url,
        default_llm_provider=settings.default_llm_provider,
        default_llm_model=settings.default_llm_model,
        llm_fallback_local=settings.llm_fallback_local,
        llm_fallback_economy=settings.llm_fallback_economy,
        llm_fallback_standard=settings.llm_fallback_standard,
        llm_fallback_premium=settings.llm_fallback_premium,
    )

    summarizer = CommunitySummarizer(platform.neo4j_client, factory)

    # Concurrency levels to test
    concurrency_levels = [1, 5, 10, 20]

    print("\n" + "="*60)
    print(f"BENCHMARKING COMMUNITY SUMMARIZATION (Batch Size: {TEST_SIZE})")
    print("="*60)

    results_table = []

    for concurrency in concurrency_levels:
        print(f"\nTurning concurrency to {concurrency}...")

        # We need a fresh semaphore/gathering logic here
        sem = asyncio.Semaphore(concurrency)

        async def _bounded_summarize(cid):
            async with sem:
                try:
                    # We just call the internal method to avoid the bulk fetch logic of summarize_all_stale
                    return await summarizer.summarize_community(cid, tenant_id)
                except Exception:
                    return None

        # Warmup / Reset? No, just run.
        start_time = time.time()

        tasks = [_bounded_summarize(cid) for cid in subset_ids]
        res = await asyncio.gather(*tasks)

        end_time = time.time()
        duration = end_time - start_time

        success_count = len([r for r in res if r])
        throughput = success_count / duration

        print(f"  -> Duration: {duration:.2f}s")
        print(f"  -> Success: {success_count}/{TEST_SIZE}")
        print(f"  -> Throughput: {throughput:.2f} communities/sec")

        results_table.append({
            "concurrency": concurrency,
            "duration": duration,
            "throughput": throughput,
            "success": success_count
        })

    print("\n" + "="*60)
    print("FINAL RESULTS")
    print("="*60)
    print(f"{'Concurrency':<15} | {'Duration (s)':<15} | {'Throughput (c/s)':<20} | {'Success Rate':<15}")
    print("-" * 75)
    for r in results_table:
        print(f"{r['concurrency']:<15} | {r['duration']:<15.2f} | {r['throughput']:<20.2f} | {r['success']}/{TEST_SIZE}")
    print("-" * 75)

    # Recommend
    best = max(results_table, key=lambda x: x['throughput'])
    print(f"\nRecommended Concurrency: {best['concurrency']}")
    print("Update your .env with:")
    print(f"COMMUNITY_SUMMARIZATION_CONCURRENCY={best['concurrency']}")

if __name__ == "__main__":
    try:
        asyncio.run(benchmark())
    except KeyboardInterrupt:
        pass
    finally:
        # Cleanup
        loop = asyncio.new_event_loop()
        loop.run_until_complete(platform.neo4j_client.close())
