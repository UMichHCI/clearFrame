import json

import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI

from .config import MODEL_MINI
from .llm import api_chat, extract_json
from .prompts import TOPICAL_GATE_FULLTEXT_SYSTEM

# Stage 1 caps extracted article bodies at 8,000 characters, so this passes the
# complete extracted body to the full-text topical gate.
GATE_FULLTEXT_CHARS = 8000
GATE_MAX_WORKERS = 8


def topical_gate(base_text: str, fulltext_df: pd.DataFrame,
                 article_type: str, client: OpenAI) -> list[dict]:
    """
    Binary same-event filter. No scoring of any kind.
    Returns one dict per candidate: {row_index, topically_relevant, reason}.

    Every candidate must already contain extracted article text. Candidates
    without text are removed before this function is called.
    """
    if fulltext_df.empty:
        return []

    system = TOPICAL_GATE_FULLTEXT_SYSTEM.format(article_type=article_type)

    candidates_payload = []
    for _, row in fulltext_df.iterrows():
        entry = {
            "row_index":     int(row.get("row_index", 0)),
            "title":         str(row.get("title", "")),
            "domain":        str(row.get("domain", "")),
            "sourcecountry": str(row.get("sourcecountry", "")),
            "seendate":      str(row.get("seendate", "")),
            "language":      str(row.get("language", "")),
            "article_text":  str(row.get("article_text", ""))[:GATE_FULLTEXT_CHARS],
        }
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
                max_tokens=800,
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

    results: list[dict] = []
    if candidates_payload:
        workers = min(GATE_MAX_WORKERS, len(candidates_payload))
        print(f"      Running topical gate as {len(candidates_payload)} one-candidate "
              f"LLM call(s), parallelism={workers}.")
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(judge_one, entry) for entry in candidates_payload]
            for future in as_completed(futures):
                results.append(future.result())

    # A missing verdict is excluded rather than silently admitted.
    seen = {r.get("row_index") for r in results}
    for entry in candidates_payload:
        row_index = int(entry["row_index"])
        if row_index not in seen:
            results.append({
                "row_index":          row_index,
                "topically_relevant": False,
                "reason":             "No verdict returned by the topical gate.",
            })

    return sorted(results, key=lambda r: r.get("row_index", 0))


