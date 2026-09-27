import os
import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.environ["GROQ_API_KEY"]
model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

response = requests.post(
    "https://api.groq.com/openai/v1/chat/completions",
    headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    },
    json={
        "model": model,
        "messages": [
            {"role": "user", "content": "Say hello in one short sentence."}
        ],
        "temperature": 0,
    },
    timeout=30,
)

print("Status code:", response.status_code)
print(response.json())