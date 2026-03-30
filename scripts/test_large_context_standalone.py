import json
import time
import urllib.request

# Configuration
OLLAMA_BASE_URL = "http://localhost:11434/v1/chat/completions"
# OLLAMA_BASE_URL = "http://172.17.0.1:11434/v1/chat/completions" # Alternative if host.docker.internal fails
MODEL = "gemma3:27b-cloud"

def generate_large_prompt(token_count=5000):
    base_text = "This is a test sentence to simulate a large context window. "
    repeat_count = (token_count // 10) + 1
    return base_text * repeat_count

def test_generation():
    print(f"Testing model: {MODEL}")
    print(f"Target URL: {OLLAMA_BASE_URL}")

    def run_test(name, token_count, options=None):
        print(f"\n--- Test: {name} (~{token_count} tokens) ---")
        long_input = generate_large_prompt(token_count)
        prompt = f"Summarize:\n\n{long_input}\n\nSummary:"

        payload = {
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7
        }
        if options:
            payload["options"] = options

        start_time = time.time()
        try:
            req = urllib.request.Request(OLLAMA_BASE_URL, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req) as response:
                duration = time.time() - start_time
                print(f"Status: {response.status}")
                print(f"Duration: {duration:.2f}s")
                print("Success!")
        except Exception as e:
            duration = time.time() - start_time
            print(f"Failed: {e}")
            print(f"Duration: {duration:.2f}s")
            if hasattr(e, 'read'):
                print(f"Body: {e.read().decode('utf-8')}")

    # 1. Test 3000 tokens (Should pass if limit is 4096)
    run_test("3000 Tokens", 3000)

    # 2. Test 5000 tokens (Should fail if limit is 4096)
    run_test("5000 Tokens", 5000)

    # 3. Test 5000 tokens with explicit num_ctx
    run_test("5000 Tokens (Explicit 16k Context)", 5000, options={"num_ctx": 16384})

if __name__ == "__main__":
    test_generation()
