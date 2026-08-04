import json

import pandas as pd
from openai import OpenAI

from .config import MODEL_MINI
from .llm import api_chat, extract_json
TOPICAL_GATE_SYSTEM = """
You are filtering candidate news articles against a base article. This is a filter,
not a ranking. Make one binary judgment per candidate and nothing more.

The base article has been classified as: {primary_type}{secondary_note}.

For each candidate, using only its title, domain, source country, date, and language,
decide: is this article about the same underlying event, situation, or subject as the
base article â€” interpreted appropriately for the base article's type?

Interpret "same" according to the article type:
  breaking_news     -> the same specific incident
  ongoing_situation -> the same ongoing situation, even at a different moment in it
  economics_policy  -> the same policy, market, or economic condition
  historical        -> the same historical events or the same background subject
  human_interest    -> the same community, population, or lived experience
  mixed             -> use judgment across the above

Be inclusive rather than strict: an article covering the same event from an unexpected
angle, or covering a direct consequence of the event, is topically relevant. An article
that merely shares a country or a broad theme is not.

Do NOT score, rank, or evaluate framing, tone, or quality. You cannot see the article
text â€” only its title and metadata. Any judgment beyond "same subject or not" would be
unfounded here.

Coverage patterns in a news system are structural â€” they follow from an outlet's position,
its audience, and its sourcing, not from the intent of journalists. Your one-sentence reason
must never suggest that an outlet or a journalist intended anything.

Return ONLY valid JSON, no markdown fences, as an object with a single key "results"
whose value is an array with one object per candidate:

{{
  "results": [
    {{
      "row_index":          <integer matching the candidate's row_index>,
      "topically_relevant": true | false,
      "reason":             "<one sentence>"
    }}
  ]
}}
"""


# Same task and same type-interpretation as the metadata gate, but the model is
# now given each candidate's article body, so the "you cannot see the text"
# constraint is dropped. Still a binary filter â€” no scoring, tone, or quality
# judgment (that remains Stage 7's job).
TOPICAL_GATE_FULLTEXT_SYSTEM = """
You are filtering candidate news articles against a base article. This is a filter,
not a ranking. Make one binary judgment per candidate and nothing more.

The base article has been classified as: {primary_type}{secondary_note}.

For each candidate you are given its title, domain, source country, date, language, and
the article's full text (which may be truncated). Decide: is this article about the same
underlying event, situation, or subject as the base article â€” interpreted appropriately
for the base article's type?

Interpret "same" according to the article type:
  breaking_news     -> the same specific incident
  ongoing_situation -> the same ongoing situation, even at a different moment in it
  economics_policy  -> the same policy, market, or economic condition
  historical        -> the same historical events or the same background subject
  human_interest    -> the same community, population, or lived experience
  mixed             -> use judgment across the above

Be inclusive rather than strict: an article covering the same event from an unexpected
angle, or covering a direct consequence of the event, is topically relevant. An article
that merely shares a country or a broad theme is not.

Judge only same-subject-or-not. Do NOT score, rank, or evaluate framing, tone, or quality
â€” that happens in a later stage.

Coverage patterns in a news system are structural â€” they follow from an outlet's position,
its audience, and its sourcing, not from the intent of journalists. Your one-sentence reason
must never suggest that an outlet or a journalist intended anything.

Return ONLY valid JSON, no markdown fences, as an object with a single key "results"
whose value is an array with one object per candidate:

{{
  "results": [
    {{
      "row_index":          <integer matching the candidate's row_index>,
      "topically_relevant": true | false,
      "reason":             "<one sentence>"
    }}
  ]
}}
"""

# Per-candidate body budget when gating on full text â€” enough of the lead to
# judge same-event without bloating the prompt across ~20 candidates.
GATE_FULLTEXT_CHARS = 1500


def topical_gate(base_text: str, candidates_df: pd.DataFrame,
                 classification: dict, client: OpenAI,
                 texts: dict[int, str] | None = None) -> list[dict]:
    """
    Binary same-event filter. No scoring of any kind.
    Returns one dict per candidate: {row_index, topically_relevant, reason}.

    If `texts` is given (row_index -> article body), the gate reads the article
    body ("fulltext" mode) and only judges candidates present in that mapping;
    every other candidate is marked not-relevant with a note. Otherwise the gate
    reads title/metadata only ("metadata" mode).
    """
    if candidates_df.empty:
        return []

    primary_type   = classification.get("primary_type", "breaking_news")
    secondary      = classification.get("secondary_type")
    secondary_note = f" (secondary type: {secondary})" if secondary else ""

    use_fulltext = texts is not None
    template     = TOPICAL_GATE_FULLTEXT_SYSTEM if use_fulltext else TOPICAL_GATE_SYSTEM
    system       = template.format(
        primary_type=primary_type,
        secondary_note=secondary_note
    )

    candidates_payload = []
    for i, (_, row) in enumerate(candidates_df.iterrows()):
        # In fulltext mode, judge only candidates we actually retrieved text for.
        if use_fulltext and i not in texts:
            continue
        entry = {
            "row_index":     i,
            "title":         str(row.get("title", "")),
            "domain":        str(row.get("domain", "")),
            "sourcecountry": str(row.get("sourcecountry", "")),
            "seendate":      str(row.get("seendate", "")),
            "language":      str(row.get("language", "")),
        }
        if use_fulltext:
            entry["article_text"] = str(texts[i])[:GATE_FULLTEXT_CHARS]
        candidates_payload.append(entry)

    # Nothing to judge (e.g. every fetch failed) â€” everyone is dropped below.
    results: list[dict] = []
    if candidates_payload:
        user_prompt = json.dumps({
            "base_article_summary": base_text[:3000],
            "candidates":           candidates_payload,
        }, ensure_ascii=False)

        raw = api_chat(
            client,
            system=system,
            user=user_prompt,
            # Full bodies make the prompt larger; give the response more room too.
            max_tokens=3000 if use_fulltext else 2000,
            model=MODEL_MINI,
            response_format={"type": "json_object"},
        )
        results = json.loads(extract_json(raw)).get("results", [])

    # A candidate the model returned no verdict for is excluded rather than
    # silently admitted â€” a missing verdict is not a passing verdict. In fulltext
    # mode, candidates without retrieved text are dropped here for the same reason.
    seen = {r.get("row_index") for r in results}
    for i in range(len(candidates_df)):
        if i not in seen:
            if use_fulltext and i not in texts:
                reason = "No full text retrieved, so the gate could not judge it."
            else:
                reason = "No verdict returned by the topical gate."
            results.append({
                "row_index":          i,
                "topically_relevant": False,
                "reason":             reason,
            })

    return sorted(results, key=lambda r: r.get("row_index", 0))

