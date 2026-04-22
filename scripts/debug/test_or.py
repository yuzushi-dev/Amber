import asyncio

from openai import AsyncOpenAI

from src.api.config import settings


async def main():
    try:
        api_key = settings.openrouter_api_key
        print(f"Key length: {len(api_key)}")
        client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            max_retries=0,
            timeout=10.0,
            default_headers={"HTTP-Referer": "https://amber.local", "X-Title": "Amber RAG"}
        )
        print("Starting OpenRouter request...")
        resp = await client.chat.completions.create(model="google/gemma-3-27b-it:free", messages=[{"role": "user", "content": "hi"}], max_tokens=10)
        print(f"Finished request: {resp.choices[0].message.content}")
    except Exception as e:
        print(f"Exception: {type(e).__name__} - {e}")

asyncio.run(main())
