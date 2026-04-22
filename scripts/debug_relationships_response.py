
import asyncio
import os
import sys

import httpx

sys.path.append(os.getcwd())

async def test_relationships():
    doc_id = "doc_1e54a28af3e548d6"
    base_url = "http://localhost:8000/v1"
    headers = {"X-API-Key": "amber-dev-key-2024"}

    print(f"Fetching relationships for {doc_id}...")
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{base_url}/documents/{doc_id}/relationships",
            headers=headers
        )

        if response.status_code != 200:
            print(f"Error: {response.status_code} - {response.text}")
            return

        data = response.json()
        print(f"Found {len(data)} relationships.")

        types = set()
        for rel in data:
            s_type = rel.get('source_type')
            t_type = rel.get('target_type')
            types.add(s_type)
            types.add(t_type)
            # Print first 5 to see structure
            if len(types) <= 5:
                 print(f"Rel: {rel['source']} ({s_type}) -> {rel['target']} ({t_type})")

        print("\nUnique Types Found:", types)

if __name__ == "__main__":
    asyncio.run(test_relationships())
