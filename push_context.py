"""
Helper to push dataset files into a running bot via /v1/context.
Avoids shell-quoting problems entirely by using Python's requests + json.

Usage:
    python push_context.py category dentists dataset/expanded/categories/dentists.json
    python push_context.py merchant m_001_drmeera_dentist_delhi dataset/expanded/merchants/m_001_drmeera_dentist_delhi.json
    python push_context.py trigger trg_001_research_digest_dentists dataset/expanded/triggers/trg_001_research_digest_dentists.json
"""
import sys
import json
import requests
from datetime import datetime, timezone

BOT_URL = "http://localhost:8000"


def push(scope: str, context_id: str, file_path: str, version: int = 1):
    with open(file_path, encoding="utf-8") as f:
        payload = json.load(f)

    body = {
        "scope": scope,
        "context_id": context_id,
        "version": version,
        "payload": payload,
        "delivered_at": datetime.now(timezone.utc).isoformat(),
    }
    resp = requests.post(f"{BOT_URL}/v1/context", json=body, timeout=10)
    print(resp.status_code, resp.json())


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python push_context.py <scope> <context_id> <file_path>")
        sys.exit(1)
    push(sys.argv[1], sys.argv[2], sys.argv[3])