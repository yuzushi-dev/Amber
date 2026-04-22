import json
import sys
import time

import requests

BASE_URL = "http://localhost:8000"
API_KEY = "amber-dev-key-2024"
HEADERS = {"X-API-Key": API_KEY}

def print_stream_content(r):
    """Parses SSE stream and prints content."""
    full_content = ""
    print("--- Stream Output ---")
    for line in r.iter_lines():
        if line:
            decoded = line.decode('utf-8')
            if decoded.startswith("data: "):
                try:
                    data_str = decoded[6:]
                    # Skip [DONE]
                    if "[DONE]" in data_str:
                        continue

                    data = json.loads(data_str)
                    # Detect if chunk or full message
                    # Agent currently sends full message in 'message' event usually, but standard SSE might be tokens
                    # We just print data if it's a string
                    if isinstance(data, str):
                        full_content += data
                        sys.stdout.write(data)
                        sys.stdout.flush()
                except:
                    pass
    print("\n---------------------")
    return full_content

def test_rag_flow():
    print("\n=== Testing RAG Flow ===")

    # 1. Initial Query
    print("[1] Sending Initial RAG Query ('WHat is Carbonio?')...")
    url = f"{BASE_URL}/v1/query/stream"
    # EventSource usually sends API Key as query param, but we add Header too just in case
    params = {"query": "WHat is Carbonio?", "api_key": API_KEY}

    conversation_id = None

    with requests.get(url, params=params, headers=HEADERS, stream=True) as r:
        if r.status_code != 200:
            print(f"FAILED: Status {r.status_code}")
            return False

        iter_lines = r.iter_lines()
        for line in iter_lines:
            if line:
                decoded = line.decode('utf-8')
                if decoded.startswith("event: conversation_id"):
                    data_line = next(iter_lines).decode('utf-8')
                    if data_line.startswith("data: "):
                        conversation_id = json.loads(data_line[6:])
                        print(f"SUCCESS: Received conversation_id: {conversation_id}")
                        break

        # Print rest of stream (Answer)
        print_stream_content(r)

    if not conversation_id:
        print("FAILED: No conversation_id received")
        return False

    # 2. Follow Up
    print(f"\n[2] Sending Follow-up ('What is Carbonio mesh?') with ID: {conversation_id}...")
    params = {"query": "What is Carbonio mesh?", "api_key": API_KEY, "conversation_id": conversation_id}

    follow_up_id = None
    with requests.get(url, params=params, headers=HEADERS, stream=True) as r:
        iter_lines = r.iter_lines()
        for line in iter_lines:
            if line:
                decoded = line.decode('utf-8')
                if decoded.startswith("event: conversation_id"):
                    data_line = next(iter_lines).decode('utf-8')
                    follow_up_id = json.loads(data_line[6:])
                    print(f"Received follow-up ID: {follow_up_id}")
                    break

        # Print rest of stream (Answer)
        print_stream_content(r)

    if follow_up_id == conversation_id:
        print("SUCCESS: RAG Threading verifies (IDs match)")
        return True
    else:
        print(f"FAILED: IDs do not match! {conversation_id} vs {follow_up_id}")
        return False

def test_agent_flow():
    print("\n=== Testing Agent Flow ===")

    # 1. Initial Agent Query
    print("[1] Sending Initial Agent Query ('WHen is my next appointment?')...")
    url = f"{BASE_URL}/v1/query/stream"
    params = {"query": "WHen is my next appointment?", "api_key": API_KEY, "agent_mode": "true"}

    conversation_id = None

    with requests.get(url, params=params, headers=HEADERS, stream=True) as r:
        iter_lines = r.iter_lines()
        for line in iter_lines:
            if line:
                decoded = line.decode('utf-8')
                if decoded.startswith("event: conversation_id"):
                    data_line = next(iter_lines).decode('utf-8')
                    conversation_id = json.loads(data_line[6:])
                    print(f"SUCCESS: Received Agent conversation_id early: {conversation_id}")
                    break

        # Print rest of stream (Answer)
        print_stream_content(r)

    if not conversation_id:
        print("FAILED: No Agent conversation_id received")
        return False

    # 2. Sticky Mode Test
    print(f"\n[2] Testing Sticky Mode ('Who is partecipating in my next appointment?') with ID: {conversation_id}...")
    params = {"query": "Who is partecipating in my next appointment?", "api_key": API_KEY, "conversation_id": conversation_id}

    is_sticky = False

    with requests.get(url, params=params, headers=HEADERS, stream=True) as r:
        # We need to scan for status, but also print content
        # This is tricky because iterator consumes stream.
        # We'll just define 'lines' and process manually

        print("--- Stream Output ---")
        lines_iter = r.iter_lines()
        for line in lines_iter:
            if line:
                decoded = line.decode('utf-8')

                # Check for sticky status
                if decoded.startswith("event: status"):
                    try:
                        data_line = next(lines_iter).decode('utf-8')
                        if "Consulting agent tools" in data_line:
                            print(f"[Status Event]: {data_line}")
                            is_sticky = True
                    except: pass
                    continue

                if decoded.startswith("data: "):
                    try:
                        data_str = decoded[6:]
                        if "[DONE]" in data_str: continue
                        data = json.loads(data_str)
                        if isinstance(data, str):
                            sys.stdout.write(data)
                            sys.stdout.flush()
                    except: pass
        print("\n---------------------")

    if is_sticky:
        print("SUCCESS: Detected Agent-specific status event (Sticky Mode works!)")

    # Verify persistence via API
    time.sleep(2) # Wait for async save
    print(f"\n[3] Verifying History Persistence via API for ID: {conversation_id}...")
    history_url = f"{BASE_URL}/v1/admin/chat/history/{conversation_id}"

    # USE HEADERS for Admin API
    with requests.get(history_url, headers=HEADERS) as r:
        if r.status_code == 200:
            data = r.json()
            history = data.get("metadata", {}).get("history", [])
            print(f"History Length: {len(history)}")
            if isinstance(history, list) and len(history) >= 2:
                 print("SUCCESS: History persisted correctly (Expected >= 2)")
                 # Optional: Print history preview
                 print("Last Message Preview:", history[-1].get("answer")[:50] + "...")
                 return True
            else:
                 print(f"FAILED: History too short. Full data: {json.dumps(data)}")
                 return False
        else:
             print(f"FAILED: History API returned {r.status_code}")
             print(r.text)
             return False

def main():
    try:
        if test_rag_flow():
            if test_agent_flow():
                print("\nALL TESTS PASSED")
                sys.exit(0)
            else:
                print("\nAGENT FLOW FAILED")
                sys.exit(1)
        else:
            print("\nRAG FLOW FAILED")
            sys.exit(1)
    except Exception as e:
        print(f"Test crashed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
