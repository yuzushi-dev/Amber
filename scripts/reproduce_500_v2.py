import urllib.request
import json
import sys

# Configuration
# This script runs INSIDE the container, so use host.docker.internal
OLLAMA_URL = "http://host.docker.internal:11434/api/chat"
MODEL = "gemma3:27b-cloud"

def test_generation(prompt_size, num_ctx=None):
    print(f"\n--- Testing with prompt size: {prompt_size} bytes, num_ctx: {num_ctx} ---")
    
    prompt = "A" * prompt_size
    
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {
            "num_ctx": num_ctx if num_ctx else 2048
        }
    }
    
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(OLLAMA_URL, data=data, headers={'Content-Type': 'application/json'})
    
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            print(f"Status Code: {response.getcode()}")
            print("Success!")
    except urllib.error.HTTPError as e:
        print(f"HTTP Error: {e.code} - {e.reason}")
        try:
            print(f"Response: {e.read().decode('utf-8')}")
        except:
            pass
    except Exception as e:
        print(f"Request Failed: {e}")

if __name__ == "__main__":
    test_generation(6500, num_ctx=2048)
    test_generation(6500, num_ctx=8192)
