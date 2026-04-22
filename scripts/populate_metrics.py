import os
import random
import time

import requests

BASE_URL = "http://localhost:8000/v1/query"

QUERIES = [
    "What is the system architecture?",
    "How does the RAG pipeline work?",
    "Show me recent logs",
    "Who are the active users?",
    "Explain the security model",
    "What is the capital of France?",
    "How to configure the database?",
    "What is the meaning of life?",
    "Test query for metrics",
    "Another random question"
]

def run():
    print(f"Sending requests to {BASE_URL}...")

    api_key = os.getenv("DEV_API_KEY", "amber-dev-key-2024") # Fallback to default dev key if not set
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": api_key
    }

    for i, q in enumerate(QUERIES):
        payload = {
            "query": q,
            "options": {
                "include_sources": True
            }
        }

        try:
            start = time.time()
            response = requests.post(BASE_URL, json=payload, headers=headers)
            elapsed = (time.time() - start) * 1000

            if response.status_code == 200:
                print(f"[{i+1}/{len(QUERIES)}] Success: '{q}' ({elapsed:.0f}ms)")
            else:
                print(f"[{i+1}/{len(QUERIES)}] Error {response.status_code}: {response.text}")

        except Exception as e:
            print(f"[{i+1}/{len(QUERIES)}] Failed: {e}")

        # Random sleep to spread out timestamps slightly
        time.sleep(random.uniform(0.5, 2.0))

if __name__ == "__main__":
    run()
