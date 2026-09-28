import json

import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI

from .config import MODEL_MINI
from .llm import api_chat, extract_json
from .prompts import TOPICAL_GATE_FULLTEXT_SYSTEM, TOPICAL_GATE_SYSTEM

# Per-candidate body budget when gating on full text â€” enough of the lead to
# judge same-event without bloating the prompt across ~20 candidates.
GATE_FULLTEXT_CHARS = 1500
GATE_MAX_WORKERS = 8


def topical_gate(base_text: str, candidates_df: pd.DataFrame,
                 article_type: str, client: OpenAI,
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

    use_fulltext = texts is not None
    template     = TOPICAL_GATE_FULLTEXT_SYSTEM if use_fulltext else TOPICAL_GATE_SYSTEM
    system       = template.format(
        article_type=article_type,
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

    def judge_one(entry: dict) -> dict:
        user_prompt = json.dumps({
            "base_article_summary": base_text[:3000],
            "candidates":           [entry],
        }, ensure_ascii=False)

        try:
            raw = api_chat(
                client,
                system=system,
                user=user_prompt,
                # One candidate per call, so the response should be short.
                max_tokens=800 if use_fulltext else 500,
                model=MODEL_MINI,
                response_format={"type": "json_object"},
            )
            parsed = json.loads(extract_json(raw))
            result = parsed.get("results", [])
            if isinstance(result, list) and result:
                result = result[0]
            if not isinstance(result, dict):
                raise ValueError("response did not contain a result object")
            result["row_index"] = int(entry["row_index"])
            return result
        except Exception as e:
            print(f"      [WARNING] Topical gate failed for row {entry['row_index']}: {e}")
            return {
                "row_index":          int(entry["row_index"]),
                "topically_relevant": False,
                "reason":             "Topical gate failed for this candidate.",
            }

    # Nothing to judge (e.g. every fetch failed) â€” everyone is dropped below.
    results: list[dict] = []
    if candidates_payload:
        workers = min(GATE_MAX_WORKERS, len(candidates_payload))
        print(f"      Running topical gate as {len(candidates_payload)} one-candidate "
              f"LLM call(s), parallelism={workers}.")
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(judge_one, entry) for entry in candidates_payload]
            for future in as_completed(futures):
                results.append(future.result())

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


