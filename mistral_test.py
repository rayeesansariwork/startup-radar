"""
Temporary Mistral quota/rate-limit probe.

Usage:
    python mistral_test.py
"""

import json
import os
import sys

import requests
from dotenv import load_dotenv


def main() -> int:
    load_dotenv()
    api_key = "9zAFjlgJmd4LdgO3v7w57roYjSxiw10A"
    if not api_key:
        print("MISTRAL_API_KEY is missing in environment/.env")
        return 2

    url = "https://api.mistral.ai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "mistral-small-latest",
        "messages": [{"role": "user", "content": "Reply with exactly: ok"}],
        "temperature": 0,
        "max_tokens": 8,
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
    except Exception as exc:
        print(f"Request failed before response: {exc}")
        return 3

    print(f"HTTP {resp.status_code}")
    text_preview = (resp.text or "")[:500]

    if resp.status_code == 200:
        data = resp.json()
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        usage = data.get("usage", {})
        print("Mistral call succeeded.")
        print(f"Model response preview: {content!r}")
        print(f"Usage: {json.dumps(usage)}")
        return 0

    # Common failure categories for quick diagnosis
    if resp.status_code == 429:
        print("Likely rate-limited or quota-exhausted (429).")
    elif resp.status_code in (401, 403):
        print("Auth/permission issue with API key.")
    elif resp.status_code == 402:
        print("Billing/payment issue (quota likely exhausted).")
    else:
        print("Non-success response from Mistral.")

    print(f"Body preview: {text_preview}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
