import re
import time

from openai import RateLimitError

from .config import MODEL_MINI
def api_chat(client, system: str, user: str, max_tokens: int = 2000,
             model: str | None = None, response_format=None) -> str:
    """Chat completion with exponential backoff on rate limits."""
    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": user}
    ]
    chosen = model or MODEL_MINI
    kwargs = {"model": chosen, "messages": messages, "max_tokens": max_tokens}
    if response_format:
        kwargs["response_format"] = response_format

    for attempt in range(6):
        try:
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content.strip()
        except RateLimitError:
            wait = 2 ** attempt
            print(f"  [Rate limit] Waiting {wait}s (attempt {attempt + 1}/6)...")
            time.sleep(wait)
    raise RuntimeError("Exceeded max retries due to rate limiting.")


def extract_json(text: str) -> str:
    """Strip markdown code fences if present."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()

