import asyncio
from openai import AsyncOpenAI
async def main():
    client = AsyncOpenAI(api_key="sk-or-test", base_url="https://openrouter.ai/api/v1", max_retries=0, timeout=5.0)
    try:
        print("Starting request...")
        await client.chat.completions.create(model="test", messages=[{"role": "user", "content": "hi"}])
        print("Finished request!")
    except Exception as e:
        print(f"Exception: {type(e).__name__} - {e}")

asyncio.run(main())
