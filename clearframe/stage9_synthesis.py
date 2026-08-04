import json

from openai import OpenAI

from .config import MODEL_FULL, STRUCTURAL_NOTE
from .llm import api_chat, extract_json
SYNTHESIS_SYSTEM = """
You are writing a short synthesis for a reader who has just read one news article. You have
been given the findings from comparing that article against several others covering the same
event, analysed through Herman and Chomsky's propaganda model.

The model is STRUCTURAL, not conspiratorial. Coverage patterns follow from an outlet's
position, its audience, and its sourcing constraints â€” not from the intent of journalists.
Never write that an outlet "hid," "chose to suppress," or "deliberately" did anything, and
never call anything "propaganda by" anyone. Describe patterns as consequences of how the news
system is structured. No editorial directive is required for these patterns to appear.

Write "overall_synthesis": 3-4 sentences on what these articles collectively let the reader
see about how this event is covered. Be specific â€” name the outlets and name the patterns.
Do not use the analytic category names, and do not use jargon. Do not hedge into generic
statements like "different outlets have different perspectives"; say what specifically differs
and what structural position accounts for it.

Return ONLY valid JSON, no markdown fences:

{
  "overall_synthesis": "<3-4 sentences>"
}
"""


def synthesize_brief(pair_analyses_selected: list[dict], base_text: str,
                     client: OpenAI) -> dict:
    """
    One call over the selected pairs' findings.
    Returns {overall_synthesis, structural_note}. structural_note is fixed, never generated.
    """
    if not pair_analyses_selected:
        return {"overall_synthesis": "", "structural_note": STRUCTURAL_NOTE}

    payload = json.dumps({
        "base_article_excerpt": base_text[:3000],
        "selected_pairs":       pair_analyses_selected,
    }, ensure_ascii=False, default=str)

    try:
        raw  = api_chat(
            client,
            system=SYNTHESIS_SYSTEM,
            user=payload,
            max_tokens=1200,
            model=MODEL_FULL,
            response_format={"type": "json_object"},
        )
        synthesis = str(json.loads(extract_json(raw)).get("overall_synthesis", "")).strip()
    except Exception as e:
        print(f"      [WARNING] Synthesis failed: {e}")
        synthesis = ""

    # The note is a constant, not model output â€” it must never drift.
    return {"overall_synthesis": synthesis, "structural_note": STRUCTURAL_NOTE}

