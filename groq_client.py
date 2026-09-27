"""
Thin wrapper around Groq's OpenAI-compatible chat completions endpoint.
"""
import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
API_KEY = os.environ["GROQ_API_KEY"]
MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")


def call_llm(system_prompt: str, user_prompt: str, temperature: float = 0.0,
             max_tokens: int = 1500, max_retries: int = 2) -> str:
    """Calls Groq, returns the assistant's text content (str).
    Retries on 429/5xx with a SHORT capped backoff — the real judge harness only
    allows 30s per call total, so we must never let backoff eat that budget."""
    payload = {
        "model": MODEL,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "reasoning_effort": "low",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    last_exc = None
    for attempt in range(max_retries):
        try:
            resp = requests.post(GROQ_URL, headers=headers, json=payload, timeout=10)
        except requests.exceptions.RequestException as e:
            last_exc = e
            time.sleep(1)
            continue

        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]

        if resp.status_code == 429 or resp.status_code >= 500:
            # Cap the wait hard — never trust Retry-After blindly, it can be 20s+.
            wait_s = min(2 ** attempt, 3)
            print(f"[groq_client] {resp.status_code}, retrying in {wait_s}s "
                  f"(attempt {attempt + 1}/{max_retries})")
            time.sleep(wait_s)
            last_exc = requests.exceptions.HTTPError(f"{resp.status_code} after retries")
            continue

        resp.raise_for_status()

    raise last_exc