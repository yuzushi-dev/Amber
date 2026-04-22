
import requests


def test_ollama_limit(model_name="gemma3:27b-cloud", num_tokens=5000):
    base_url = "http://host.docker.internal:11434/v1/chat/completions"

    # Simulate a large prompt roughly. 1 word approx 1.3 tokens usually, but let's just make a long repeating string.
    # 4 chars per token roughly.
    prompt_text = "entity relationship " * (num_tokens // 2)

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": f"Summarize this: {prompt_text}"}
        ],
        "temperature": 0.0
    }

    print(f"Testing {model_name} with approx {num_tokens} tokens...")
    try:
        response = requests.post(base_url, json=payload, timeout=120)
        print(f"Status Code: {response.status_code}")
        if response.status_code != 200:
            print(f"Error Response: {response.text}")
        else:
            print("Success!")
            # print(response.json())
    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    # Test with increasing sizes
    for size in [2000, 8000, 16000, 32000, 128000]:
        print(f"\n--- Testing size: {size} ---")
        test_ollama_limit(num_tokens=size)
