
import requests
import json
import sys

# Configuration
OLLAMA_BASE_URL = "http://localhost:11434/v1"
MODEL = "gemma3:27b-cloud"

def generate_large_prompt(token_count=5000):
    # Rough approximation: 1 word ~= 1.3 tokens. 
    # We want to generate enough text to hit potential context limits.
    # 30 * 100 words ~= 3000 words ~= 4000 tokens
    # Let's make it bigger to be safe.
    
    base_text = "This is a test sentence to simulate a large context window for the community summarization task. "
    repeat_count = (token_count // 5) + 1
    return base_text * repeat_count

def test_generation():
    print(f"Testing model: {MODEL}")
    print(f"Base URL: {OLLAMA_BASE_URL}")
    
    # 1. Test Small Prompt (Baseline)
    print("\n--- Test 1: Small Prompt ---")
    try:
        payload = {
            "model": MODEL,
            "messages": [{"role": "user", "content": "Hello, are you working?"}],
            "temperature": 0.7
        }
        response = requests.post(f"{OLLAMA_BASE_URL}/chat/completions", json=payload)
        print(f"Status: {response.status_code}")
        if response.status_code != 200:
            print(f"Error: {response.text}")
        else:
            print("Success!")
    except Exception as e:
        print(f"Exception: {e}")

    # 2. Test Large Prompt (Simulating Community Summary)
    print("\n--- Test 2: Large Prompt (~6k tokens) ---")
    long_input = generate_large_prompt(6000)
    prompt = f"Please summarize the following text:\n\n{long_input}\n\nSummary:"
    
    try:
        payload = {
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "options": {
                "num_ctx": 16384 # Requesting generous context
            }
        }
        print("Sending request...")
        response = requests.post(f"{OLLAMA_BASE_URL}/chat/completions", json=payload)
        print(f"Status: {response.status_code}")
        if response.status_code != 200:
            print(f"Error Body: {response.text}")
        else:
            print("Success! (Large context accepted)")
            # print(response.json()['choices'][0]['message']['content'][:100] + "...")
            
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    test_generation()
