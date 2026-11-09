import re
import time

from openai import RateLimitError

from .config import MODEL_MINI, MODEL_REASONING
def api_chat(client, system: str, user: str, max_tokens: int = 2000,
             model: str | None = None, response_format=None) -> str:
    """Chat completion with model-specific reasoning and rate-limit backoff.

    max_tokens is the stage's answer budget. For configured reasoning models,
    add capacity for internal reasoning to the total completion limit.
    """
    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": user}
    ]
    chosen = model or MODEL_MINI
    kwargs = {"model": chosen, "messages": messages}
    if chosen in MODEL_REASONING:
        effort, reasoning_capacity = MODEL_REASONING[chosen]
        kwargs["reasoning_effort"] = effort
        kwargs["max_completion_tokens"] = max_tokens + reasoning_capacity
    else:
        kwargs["max_completion_tokens"] = max_tokens
    if response_format:
        kwargs["response_format"] = response_format

    for attempt in range(6):
        try:
            resp = client.chat.completions.create(**kwargs)
            choice = resp.choices[0]
            if choice.finish_reason != "stop":
                raise RuntimeError(
                    f"{chosen} did not complete its response (finish_reason={choice.finish_reason})."
                )
            if choice.message.refusal:
                raise RuntimeError(f"{chosen} refused the requested analysis.")
            content = choice.message.content
            if not content or not content.strip():
                raise RuntimeError(f"{chosen} returned an empty response.")
            return content.strip()
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

