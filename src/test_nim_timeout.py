import asyncio
from openai import AsyncOpenAI
import time

async def main():
    start = time.time()
    # Explicitly test the timeout behavior against NIM
    client = AsyncOpenAI(
        api_key="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", 
        base_url="https://integrate.api.nvidia.com/v1", 
        max_retries=0, 
        timeout=10.0
    )
    try:
        print("Starting NIM request...")
        await client.chat.completions.create(model="google/gemma-3-27b-it", messages=[{"role": "user", "content": "hi"}], max_tokens=10)
        print(f"Finished request in {time.time() - start:.2f}s!")
    except Exception as e:
        print(f"Exception after {time.time() - start:.2f}s: {type(e).__name__} - {e}")

asyncio.run(main())
