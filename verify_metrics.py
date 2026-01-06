import asyncio

from src.core.metrics.collector import MetricsCollector


async def verify_metrics():
    print("Verifying MetricsCollector...")

    # Use a dummy redis URL or temporary buffer-only mode if no redis
    # The collector defaults to memory buffer if redis fails, which is fine for this test
    collector = MetricsCollector(redis_url="redis://localhost:6379/99") # Use db 99 for test

    query_id = "test_verification_id"

    # Simulating a tracked query
    print(f"Tracking query {query_id}...")
    async with collector.track_query(query_id, "test_tenant", "Verify implementation") as metrics:
        # Populate new fields
        metrics.input_tokens = 50
        metrics.output_tokens = 25
        metrics.tokens_used = 75
        metrics.provider = "test_provider"
        metrics.model = "gpt-4-test"
        metrics.success = True
        metrics.conversation_id = "conv_123"

        # Simulate latency
        await asyncio.sleep(0.01)

    print("Query tracked. Fetching recent...")

    # Fetch recent
    recent = await collector.get_recent(tenant_id="test_tenant", limit=10)

    found = False
    for m in recent:
        if m.query_id == query_id:
            found = True
            print("✅ Metric found!")
            print(f"   Provider: {m.provider}")
            print(f"   Input Tokens: {m.input_tokens}")
            print(f"   Output Tokens: {m.output_tokens}")
            print(f"   Success: {m.success}")
            print(f"   Conversation ID: {m.conversation_id}")

            assert m.provider == "test_provider", "Provider mismatch"
            assert m.input_tokens == 50, "Input tokens mismatch"
            assert m.output_tokens == 25, "Output tokens mismatch"
            assert m.success, "Success status mismatch"
            assert m.conversation_id == "conv_123", "Conversation ID mismatch"
            break

    if not found:
        print("❌ Metric NOT found in recent list!")
        exit(1)

    await collector.close()
    print("Verification passed successfully.")

if __name__ == "__main__":
    asyncio.run(verify_metrics())
