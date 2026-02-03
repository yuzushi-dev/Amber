
import asyncio
import os
from openai import AsyncOpenAI

async def debug_stream():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY not set")
        return

    client = AsyncOpenAI(api_key=api_key)
    
    model = "gpt-5-nano"
    print(f"Testing stream with model: {model}")

    try:
        stream = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Explain quantum entanglement briefly."}],
            stream=True,
            temperature=1.0,
            max_completion_tokens=1000 
        )

        print("--- Stream Started ---")
        async for chunk in stream:
            delta = chunk.choices[0].delta
            print(f"Chunk: content={repr(delta.content)}, extra={delta.model_dump()}")
            
        print("--- Stream Finished ---")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(debug_stream())
