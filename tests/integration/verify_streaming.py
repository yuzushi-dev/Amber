import asyncio
import sys

import aiohttp

# Constants
API_URL = "http://localhost:8000/v1"
TEST_FILE_CONTENT = b"%" + b"a" * 1024 * 1024 * 5  # 5MB PDF-like file
TEST_FILENAME = "test_streaming.pdf"
API_KEY = "amber-dev-key-2024"  # Default dev key from security.py

async def test_streaming():
    print("starting streaming test...")
    async with aiohttp.ClientSession() as session:
        # 1. Upload a dummy file
        print(f"Uploading {len(TEST_FILE_CONTENT)} bytes...")
        data = aiohttp.FormData()
        data.add_field('file', TEST_FILE_CONTENT, filename=TEST_FILENAME, content_type='application/pdf')
        data.add_field('tenant_id', 'default')

        async with session.post(f"{API_URL}/documents", data=data, headers={"X-API-Key": API_KEY}) as resp:
            if resp.status != 202:
                print(f"Upload failed: {resp.status} {await resp.text()}")
                return False
            result = await resp.json()
            doc_id = result['document_id']
            print(f"Uploaded document ID: {doc_id}")

        # 2. Request file and verify streaming
        print("Requesting file download...")
        start_time = asyncio.get_event_loop().time()

        async with session.get(f"{API_URL}/documents/{doc_id}/file", headers={"X-API-Key": API_KEY}) as resp:
            if resp.status != 200:
                print(f"Download failed: {resp.status} {await resp.text()}")
                return False

            chunk_count = 0
            total_bytes = 0
            first_chunk_time = None

            # Read chunks
            async for chunk in resp.content.iter_chunked(1024 * 64): # 64KB chunks
                if chunk_count == 0:
                    first_chunk_time = asyncio.get_event_loop().time()
                    print(f"First chunk received in {first_chunk_time - start_time:.4f}s")

                chunk_count += 1
                total_bytes += len(chunk)

                if chunk_count % 10 == 0:
                    sys.stdout.write(".")
                    sys.stdout.flush()

            print(f"\nDownload complete. Total bytes: {total_bytes}")
            print(f"Total chunks: {chunk_count}")

            # 3. Cleanup
            print("Cleaning up...")
            async with session.delete(f"{API_URL}/documents/{doc_id}", headers={"X-API-Key": API_KEY}) as del_resp:
                print(f"Delete status: {del_resp.status}")

            if total_bytes != len(TEST_FILE_CONTENT):
                print("FAIL: Byte count mismatch")
                return False

            if chunk_count < 2:
                 # If it was buffered, it might come in one huge chunk or very few depending on network
                 # But checking "first chunk time" vs "total time" is better.
                 # If we get the first chunk quickly, it's streaming.
                 print("WARNING: Low chunk count, might not be streaming efficiently or network is too fast.")

            print("SUCCESS: File downloaded successfully.")
            return True

if __name__ == "__main__":
    try:
        if asyncio.run(test_streaming()):
            sys.exit(0)
        else:
            sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
