import json

from openai import OpenAI

from .llm import api_chat, extract_json
CLASSIFICATION_SYSTEM = """
You are classifying a news article to understand what kind of story it is.
Use your own judgment. Return ONLY valid JSON. No preamble, no markdown fences.

Your goal is to identify the primary nature of the article so that relevance
scoring later can be interpreted appropriately. This is not a rigid test â€”
use the categories below as a thinking guide, not a checklist.

Categories to consider (pick the one that best describes the article's core focus):
  - breaking_news     : Something specific just happened and coverage is time-sensitive
  - ongoing_situation : A situation that has been developing over time with no single trigger
  - economics_policy  : Primarily about economic conditions, policy, legislation, or trade
  - historical        : Primarily about past events or background context
  - human_interest    : Primarily about how people or communities are experiencing something
  - mixed             : Genuinely spans more than one category

Some questions that might help you decide (use them as a guide, not a formula):
  - Is there a specific triggering event, or is this about a broader situation?
  - Is time a critical factor in the article's relevance, or would it still matter months from now?
  - Is the focus on data, policy, and institutions â€” or on people and lived experience?
  - Does the article describe something that happened recently, or does it explain background?

Output schema:
{
  "primary_type":   "breaking_news | ongoing_situation | economics_policy | historical | human_interest | mixed",
  "secondary_type": "<type or null if no meaningful secondary>",
  "justification":  "<1-2 sentences explaining your reasoning in plain language>"
}
"""

def classify_article(article_text: str, client: OpenAI) -> dict:
    raw = api_chat(
        client,
        system=CLASSIFICATION_SYSTEM,
        user=f"Classify this article:\n\n{article_text[:4000]}",
        max_tokens=600
    )
    return json.loads(extract_json(raw))

