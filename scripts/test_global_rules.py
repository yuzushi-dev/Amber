#!/usr/bin/env python3
"""
Test Global Rules: Document Retrieval Evaluation (SSE Version)
==============================================================
Sends 8 test questions via GET /v1/query/stream (SSE) and evaluates
whether retrieved source documents match the expected product category.
"""

import json
import sys

import requests

API_BASE = "http://localhost:8000/v1/query/stream"
API_KEY = "amber-dev-key-2024"

QUESTIONS = [
    {
        "id": 1,
        "question": "What would happen if I do not set DNS records before Carbonio CE installation?",
        "expected_category": "CE",
    },
    {
        "id": 2,
        "question": "Should I follow any order of components during Carbonio CE Installation?",
        "expected_category": "CE",
    },
    {
        "id": 3,
        "question": "I forgot my consul password. How could I retrieve it?",
        "expected_category": "CARBONIO",
    },
    {
        "id": 4,
        "question": "What is the Admin Panel login details after new installation?",
        "expected_category": "CE_OR_CARBONIO",
    },
    {
        "id": 5,
        "question": "After a fresh installation of Carbonio CE, I sent an email from one local user to another local user. The test email landed on the Junk folder. Where should I look first?",
        "expected_category": "CE",
    },
    {
        "id": 6,
        "question": "I do not want to include SPAM folder contents in my search result. How can I do it?",
        "expected_category": "USER",
    },
    {
        "id": 7,
        "question": "How can I configure delegated admin in Carbonio CE?",
        "expected_category": "CE",
    },
    {
        "id": 8,
        "question": "how can I use this command? zimbraMtaRelayHost",
        "expected_category": "CE_OR_CARBONIO",
    },
]


def classify_source_title(title: str) -> str:
    """Classify a source title into CE, CARBONIO, USER, or UNKNOWN."""
    if not title or title == "Untitled":
        return "UNKNOWN"
    t = title.lower()

    # User guide detection
    if "user guide" in t or "user_guide" in t or "carbonio_user" in t or "user_docs" in t:
        return "USER"
    # CE detection
    if "carbonio ce" in t or "carbonio-ce" in t or "_ce_" in t or " ce " in t or t.endswith(" ce") or t.startswith("ce_") or t.startswith("ce "):
        return "CE"
    # Generic Carbonio (admin guide)
    if "carbonio" in t or "admin" in t or t.startswith("carbonio_docs"):
        return "CARBONIO"
    return "UNKNOWN"


def parse_sse_sources(response_text: str) -> tuple[list[dict], str]:
    """Parse SSE events to extract sources and answer."""
    sources = []
    answer_tokens = []

    for line in response_text.split("\n"):
        line = line.strip()
        if line.startswith("event: "):
            current_event = line[7:]
        elif line.startswith("data: ") and current_event:
            data_str = line[6:]
            try:
                data = json.loads(data_str)
            except (json.JSONDecodeError, TypeError):
                continue

            if current_event == "sources" and isinstance(data, list):
                sources = data
            elif current_event == "token" and isinstance(data, str):
                answer_tokens.append(data)

    answer = "".join(answer_tokens)
    return sources, answer


def evaluate_match(expected: str, source_categories: list[str]) -> tuple[bool, str]:
    """Evaluate if retrieved sources match the expected category."""
    if not source_categories:
        return False, "NO_SOURCES"

    counts = {}
    for cat in source_categories:
        if cat != "UNKNOWN":
            counts[cat] = counts.get(cat, 0) + 1

    if not counts:
        return False, "UNKNOWN"

    dominant = max(counts, key=counts.get)

    if expected == "CE_OR_CARBONIO":
        return dominant in ("CE", "CARBONIO"), dominant
    return dominant == expected, dominant


def run_test(q: dict) -> dict:
    """Run a single test question via SSE streaming endpoint."""
    print(f"\n{'='*70}")
    print(f"Q{q['id']}: {q['question'][:80]}")
    print(f"Expected: {q['expected_category']}")
    print(f"{'='*70}")

    try:
        import time
        time.sleep(5)

        # Use a fresh session and close connection to avoid reset
        session = requests.Session()
        resp = session.get(
            API_BASE,
            params={"query": q["question"], "api_key": API_KEY},
            headers={"Accept": "text/event-stream", "Connection": "close"},
            timeout=180,
            stream=True,
        )


        if resp.status_code != 200:
            print(f"  ERROR: HTTP {resp.status_code}")
            return {"id": q["id"], "status": "ERROR"}

        sources = []
        answer_tokens = []
        current_event = None

        for line_bytes in resp.iter_lines():
            if not line_bytes:
                continue

            line = line_bytes.decode('utf-8').strip()

            if not line or line.startswith(":"):
                continue
            if line.startswith("event: "):
                current_event = line[7:].strip()
            elif line.startswith("data: "):
                data_str = line[6:]
                try:
                    data = json.loads(data_str)
                except (json.JSONDecodeError, TypeError):
                    continue

                if current_event == "sources" and isinstance(data, list):
                    sources = data
                elif current_event == "token" and isinstance(data, str):
                    answer_tokens.append(data)

        answer = "".join(answer_tokens)


        print(f"\n  Answer: {answer[:150]}...")
        print(f"\n  Sources ({len(sources)}):")

        source_categories = []
        for s in sources:
            title = s.get("title", "Untitled")
            cat = classify_source_title(title)
            source_categories.append(cat)
            print(f"    [{cat:>10}] {title[:70]}")

        match, dominant = evaluate_match(q["expected_category"], source_categories)
        icon = "✅" if match else "❌"
        print(f"\n  {icon} expected={q['expected_category']}, dominant={dominant}")

        return {
            "id": q["id"],
            "expected": q["expected_category"],
            "dominant": dominant,
            "match": match,
            "num_sources": len(sources),
            "categories": source_categories,
        }

    except Exception as e:
        print(f"  ERROR: {e}")
        return {"id": q["id"], "status": "ERROR", "error": str(e)}


def main():
    print("=" * 70)
    print("GLOBAL RULES TEST: Document Retrieval Category Evaluation (SSE)")
    print("=" * 70)

    results = []
    for q in QUESTIONS:
        result = run_test(q)
        results.append(result)

    # Summary
    print("\n\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"{'Q#':<5} {'Expected':<18} {'Dominant':<18} {'Result':<8} {'All Categories'}")
    print("-" * 70)

    passed = 0
    total = 0
    for r in results:
        if r.get("status") in ("ERROR", "TIMEOUT"):
            print(f"Q{r['id']:<4} {'ERROR':<18}")
            continue
        total += 1
        icon = "✅" if r["match"] else "❌"
        if r["match"]:
            passed += 1
        cats = ", ".join(r.get("categories", []))
        print(f"Q{r['id']:<4} {r['expected']:<18} {r['dominant']:<18} {icon:<8} {cats}")

    print("-" * 70)
    print(f"Score: {passed}/{total}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
