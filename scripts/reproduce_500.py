import requests
import json
import sys

# Configuration
OLLAMA_URL = "http://host.docker.internal:11434/v1/chat/completions"
# OLLAMA_URL = "http://localhost:11434/v1/chat/completions" # Use this if running on valid host
MODEL = "gemma3:27b-cloud"

def test_generation(prompt_size, num_ctx=None):
    print(f"\n--- Testing with prompt size: {prompt_size} bytes, num_ctx: {num_ctx} ---")
    
    # Create a prompt of approximately 'prompt_size' bytes
    prompt = "A" * prompt_size
    
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False
    }
    
    if num_ctx:
        # For /v1/chat/completions, options are often passed differently depending on the backend,
        # but for Ollama native API it's 'options'. For OpenAI compat, it might be 'max_tokens' or similar?
        # Actually Ollama's OpenAI compat endpoint might NOT support 'options' directly in the top level.
        # We might need to use the raw /api/chat endpoint to pass 'options'.
        # Let's try native /api/chat if /v1 fails, or check how to pass options in /v1.
        # Usually OpenAI API doesn't have 'num_ctx'.
        # But Ollama documents that we can pass 'options' map in the request body even for /v1/chat/completions?
        # Let's check successful requests or docs. 
        # Actually, let's use the NATIVE Ollama endpoint for this test to be sure about parameters.
        pass

    # Let's switch to native endpoint for better control over options
    url = OLLAMA_URL.replace("/v1/chat/completions", "/api/chat")
    
    native_payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {
            "num_ctx": num_ctx if num_ctx else 2048 # Default is 2048
        }
    }
    
    try:
        response = requests.post(url, json=native_payload, timeout=60)
        print(f"Status Code: {response.status_code}")
        if response.status_code != 200:
            print(f"Error Response: {response.text}")
        else:
            print("Success!")
    except Exception as e:
        print(f"Request Failed: {e}")

if __name__ == "__main__":
    # Test 1: 6KB with default context (should fail if 2048 is too small or if model crashes)
    # 6000 chars is roughly 1500 tokens? 2048 should cover it.
    # But maybe the internal representation is larger.
    # The user found failure at 6144 bytes.
    
    test_generation(6500, num_ctx=2048)
    
    # Test 2: 6KB with larger context
    test_generation(6500, num_ctx=8192)
