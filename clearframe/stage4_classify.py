import json

from openai import OpenAI

from .llm import api_chat, extract_json
from .prompts import CLASSIFICATION_SYSTEM


def classify_article(article_text: str, client: OpenAI) -> dict:
    raw = api_chat(
        client,
        system=CLASSIFICATION_SYSTEM,
        user=f"Classify this article:\n\n{article_text[:4000]}",
        max_tokens=600
    )
    return json.loads(extract_json(raw))


