"""
Helper to simulate a merchant/customer reply via /v1/reply.
Usage:
    python send_reply.py <conversation_id> <merchant_id> "<message text>"
"""
import sys
import requests
from datetime import datetime, timezone

BOT_URL = "http://localhost:8000"

if __name__ == "__main__":
    conversation_id, merchant_id, message = sys.argv[1], sys.argv[2], sys.argv[3]
    body = {
        "conversation_id": conversation_id,
        "merchant_id": merchant_id,
        "customer_id": None,
        "from_role": "merchant",
        "message": message,
        "received_at": datetime.now(timezone.utc).isoformat(),
        "turn_number": 2,
    }
    resp = requests.post(f"{BOT_URL}/v1/reply", json=body, timeout=30)
    print(resp.status_code)
    print(resp.json())