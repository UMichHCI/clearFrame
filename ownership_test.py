#!/usr/bin/env python3
"""
ownership_test.py — Research validation harness for LLM-reported news outlet ownership.

This is a STANDALONE validation script. It is NOT part of the main ClearFrame
pipeline. Its purpose is to measure whether LLMs can reliably report news outlet
ownership from their pretraining data, by quantifying:

  1. Intra-model consistency — does the same model give the same answer across
     repeated runs for the same domain?
  2. Cross-model agreement — do different models agree with each other?
  3. Ground-truth accuracy — do LLM answers match manually researched facts?

Run:
  pip install openai python-dotenv
  python ownership_test.py

Requires OPENAI_API_KEY in the environment (or a .env file).
"""

from __future__ import annotations

import os
import re
import json
import time
import datetime
from collections import Counter

from dotenv import load_dotenv
from openai import OpenAI, RateLimitError

load_dotenv()

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

RESULTS_DIR = "ownership_test_results"

# Fields returned by the ownership prompt, in display order. The consistency
# scoring and comparison logic iterate over this list.
OWNERSHIP_FIELDS = [
    "outlet_name",
    "owner",
    "parent_company",
    "ownership_type",
    "other_holdings",
    "state_relationship",
    "confidence",
    "as_of",
]

# ─────────────────────────────────────────────
# OWNERSHIP EXTRACTION PROMPT
# ─────────────────────────────────────────────

OWNERSHIP_SYSTEM = """\
You are a research assistant reporting what your training data contains about \
the ownership and institutional position of news outlets. You will be given the \
domain name of a news outlet.

Report ONLY what you actually know from your training data. Do NOT guess, \
extrapolate, or infer. If you do not know something, say "unknown". Honesty \
about your confidence is more important than completeness — it is far better to \
say "unknown" than to produce a plausible-sounding but uncertain answer.

Return a JSON object with EXACTLY these fields:

- "outlet_name": the common name of the outlet.

- "owner": the direct owner of the outlet — a person, family, company, \
foundation, or government. If unknown, the string "unknown".

- "parent_company": the ultimate parent company or entity, if different from the \
direct owner. If there is none, "none". If unknown, "unknown".

- "ownership_type": exactly one of: "private_individual", "private_company", \
"public_company", "nonprofit_foundation", "state_owned", \
"state_funded_independent", "cooperative", "unknown".

- "other_holdings": an array of short strings describing other significant \
holdings or business interests of the owner or parent company that could \
plausibly shape editorial incentives (e.g. "owns a major telecom operator", \
"defense contracting"). Empty array if unknown.

- "state_relationship": one sentence describing any relationship to a \
government — funding, regulation, licensing dependence — or "none known".

- "confidence": exactly one of "high", "medium", "low". "high" means this \
information is well-established and stable in your training data. "low" means \
you are uncertain or the information may be outdated.

- "as_of": your best estimate of when this ownership information was current \
(e.g. "2023", "as of 2021"), since ownership changes over time and your \
training data has a cutoff.

Return ONLY valid JSON. No preamble, no markdown fences.\
"""

# ─────────────────────────────────────────────
# GROUND TRUTH
# ─────────────────────────────────────────────

# Manually verified ownership data. This is the gold standard the LLM answers are
# checked against. Enter an entry here AFTER researching each outlet through:
#   - the outlet's own "About" / "Ownership" / "Imprint" page
#   - Wikipedia (cross-check its cited sources, don't trust it blindly)
#   - Media Ownership Monitor (https://mom-gmr.org)
#   - corporate filings / company registries where available
#
# Each entry should use the SAME field structure as the LLM output
# (see OWNERSHIP_FIELDS). Leave a field as "unknown" only if research was
# genuinely inconclusive — this dict is supposed to be the trusted reference.
#
# Example shape (fill in real researched values):
#   "nytimes.com": {
#       "outlet_name": "The New York Times",
#       "owner": "The New York Times Company",
#       "parent_company": "none",
#       "ownership_type": "public_company",
#       "other_holdings": ["The Athletic", "Wirecutter", "Wordle"],
#       "state_relationship": "none known",
#       "confidence": "high",
#       "as_of": "2024",
#   },
GROUND_TRUTH: dict[str, dict] = {
    # <domain>: { ...researched fields... }
}

# ─────────────────────────────────────────────
# MODEL PROVIDER CONFIG
# ─────────────────────────────────────────────
#
# To add a new provider later (e.g. Claude, Gemini), implement its call_* stub
# below and add an entry here. Each "call" must have signature:
#     call(model_id: str, system: str, user: str) -> str   # returns raw text
# The harness handles JSON parsing and fence stripping itself, so call_*
# functions only need to return the model's raw text response.


def _openai_client() -> OpenAI:
    """Lazily construct a shared OpenAI client."""
    global _OPENAI_CLIENT
    try:
        return _OPENAI_CLIENT
    except NameError:
        _OPENAI_CLIENT = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        return _OPENAI_CLIENT


def call_openai(model_id: str, system: str, user: str) -> str:
    """OpenAI chat completion with exponential backoff on rate limits.

    Mirrors the api_chat helper pattern from the main ClearFrame pipeline:
    exponential backoff, response_format=json_object.
    """
    client = _openai_client()
    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": user},
    ]
    kwargs = {
        "model": model_id,
        "messages": messages,
        "max_tokens": 800,
        "response_format": {"type": "json_object"},
    }
    for attempt in range(6):
        try:
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content.strip()
        except RateLimitError:
            wait = 2 ** attempt
            print(f"  [Rate limit] Waiting {wait}s (attempt {attempt + 1}/6)...")
            time.sleep(wait)
    raise RuntimeError("Exceeded max retries due to rate limiting.")


def call_anthropic(model_id: str, system: str, user: str) -> str:
    """STUB — Claude via the Anthropic API.

    To implement: `pip install anthropic`, set ANTHROPIC_API_KEY, construct an
    anthropic.Anthropic() client, and call client.messages.create(...) with the
    system prompt passed as the top-level `system=` argument (not a message).
    Anthropic has no response_format=json_object, so instruct JSON in the prompt
    (OWNERSHIP_SYSTEM already does) and run the result through extract_json().
    Return the response text.
    """
    raise NotImplementedError(
        "call_anthropic needs ANTHROPIC_API_KEY and an anthropic.Anthropic() "
        "client set up. See docstring."
    )


def call_gemini(model_id: str, system: str, user: str) -> str:
    """STUB — Gemini via the Google Generative AI API.

    To implement: `pip install google-generativeai`, set GOOGLE_API_KEY,
    configure genai with the key, build a GenerativeModel(model_id,
    system_instruction=system), call generate_content(user), and return
    response.text. Gemini can emit JSON via a response_mime_type config, or just
    run the text through extract_json().
    """
    raise NotImplementedError(
        "call_gemini needs GOOGLE_API_KEY and a google.generativeai client set "
        "up. See docstring."
    )


# provider label → {"model": <model id>, "call": <call fn>}
MODELS: dict[str, dict] = {
    "gpt-4o":      {"model": "gpt-4o",      "call": call_openai},
    "gpt-4o-mini": {"model": "gpt-4o-mini", "call": call_openai},
    # Add later — stubs already wired:
    # "claude":    {"model": "claude-opus-4-8",  "call": call_anthropic},
    # "gemini":    {"model": "gemini-1.5-pro",   "call": call_gemini},
}

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────


def extract_json(text: str) -> str:
    """Strip markdown code fences if present. (Same as the main pipeline.)"""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def query_ownership(domain: str, model_id: str, call_fn) -> dict:
    """Run the ownership prompt once and parse the JSON response.

    Returns the parsed dict, or a dict with an "_error" key if parsing failed
    (so a single bad response does not abort an entire multi-run sweep).
    """
    user = f"News outlet domain: {domain}"
    try:
        raw = call_fn(model_id, OWNERSHIP_SYSTEM, user)
        return json.loads(extract_json(raw))
    except json.JSONDecodeError as e:
        return {"_error": f"JSON parse failed: {e}", "_raw": raw}
    except Exception as e:  # network, API, etc. — keep the sweep alive
        return {"_error": f"{type(e).__name__}: {e}"}


def _normalize_scalar(v) -> str:
    """Case-insensitive, whitespace-stripped string form of a scalar field."""
    return str(v).strip().lower()


def _normalize_holdings(v) -> frozenset:
    """other_holdings compared as a set of normalized strings."""
    if not isinstance(v, list):
        return frozenset()
    return frozenset(_normalize_scalar(item) for item in v)


def _field_key(field: str, value):
    """Comparable, hashable representation of one field's value."""
    if field == "other_holdings":
        return _normalize_holdings(value)
    return _normalize_scalar(value)


def _fmt_field(field: str, value) -> str:
    """Compact human-readable rendering of a field value for tables."""
    if field == "other_holdings":
        if isinstance(value, list):
            return "[" + ", ".join(str(x) for x in value) + "]" if value else "[]"
        return str(value)
    return str(value)


# ─────────────────────────────────────────────
# 1. INTRA-MODEL CONSISTENCY
# ─────────────────────────────────────────────


def test_ownership_consistency(domains: list[str],
                               runs_per_domain: int = 5,
                               model_label: str = "gpt-4o") -> dict:
    """Run the ownership prompt `runs_per_domain` times per domain on one model
    and measure how consistent the answers are across runs.

    Returns a dict keyed by domain:
        { domain: {"runs": [...], "consistency": float, "field_agreement": {...}} }
    """
    cfg = MODELS[model_label]
    model_id, call_fn = cfg["model"], cfg["call"]

    results: dict[str, dict] = {}

    for domain in domains:
        print("\n" + "=" * 70)
        print(f"INTRA-MODEL CONSISTENCY — {domain}  ({model_label}, "
              f"{runs_per_domain} runs)")
        print("=" * 70)

        runs = []
        for i in range(runs_per_domain):
            print(f"  Run {i + 1}/{runs_per_domain}...", flush=True)
            runs.append(query_ownership(domain, model_id, call_fn))

        # Per-field agreement across runs.
        field_agreement: dict[str, bool] = {}
        agreed_count = 0
        for field in OWNERSHIP_FIELDS:
            keys = {_field_key(field, r.get(field)) for r in runs}
            agrees = len(keys) == 1
            field_agreement[field] = agrees
            if agrees:
                agreed_count += 1

        consistency = agreed_count / len(OWNERSHIP_FIELDS)

        results[domain] = {
            "model": model_label,
            "runs": runs,
            "field_agreement": field_agreement,
            "consistency": consistency,
        }

        _print_consistency_report(domain, runs, field_agreement, consistency)

    return results


def _print_consistency_report(domain, runs, field_agreement, consistency):
    """Per-domain report: each field, the answer from each run side by side,
    whether the runs agree, and the overall consistency score."""
    n = len(runs)
    print(f"\n  Per-field agreement for {domain}:")
    for field in OWNERSHIP_FIELDS:
        mark = "AGREE   " if field_agreement[field] else "DISAGREE"
        print(f"    [{mark}] {field}")
        for i, r in enumerate(runs):
            val = r.get("_error") or _fmt_field(field, r.get(field, "<missing>"))
            print(f"        run{i + 1}: {val}")
    print(f"\n  >> Consistency score: {consistency:.2f}  "
          f"({sum(field_agreement.values())}/{len(OWNERSHIP_FIELDS)} fields "
          f"agreed across {n} runs)")


# ─────────────────────────────────────────────
# 2. CROSS-MODEL COMPARISON
# ─────────────────────────────────────────────


def test_across_models(domains: list[str]) -> dict:
    """Run the ownership prompt once per domain on each configured model and
    compare. Returns { domain: {model_label: answer_dict, ...} }."""
    results: dict[str, dict] = {}

    for domain in domains:
        print("\n" + "=" * 70)
        print(f"CROSS-MODEL COMPARISON — {domain}")
        print("=" * 70)

        per_model: dict[str, dict] = {}
        for label, cfg in MODELS.items():
            print(f"  Querying {label}...", flush=True)
            try:
                per_model[label] = query_ownership(domain, cfg["model"], cfg["call"])
            except NotImplementedError as e:
                print(f"    [skipped] {label}: {e}")
                per_model[label] = {"_error": f"NotImplementedError: {e}"}

        results[domain] = per_model
        _print_cross_model_table(domain, per_model)

    return results


def _print_cross_model_table(domain, per_model):
    """Comparison table per domain: what each model said for each field, flagging
    disagreements between models."""
    labels = list(per_model.keys())
    col_w = 32

    header = "  " + f"{'field':<20}" + "".join(f"{lab:<{col_w}}" for lab in labels) + "agree?"
    print("\n" + header)
    print("  " + "-" * (20 + col_w * len(labels) + 6))

    for field in OWNERSHIP_FIELDS:
        keys = set()
        cells = []
        for lab in per_model:
            ans = per_model[lab]
            if "_error" in ans:
                cells.append("<error>")
                keys.add(("_error",))
            else:
                val = ans.get(field, "<missing>")
                cells.append(_fmt_field(field, val)[: col_w - 2])
                keys.add(_field_key(field, val))
        agree = "OK" if len(keys) == 1 else "DIFFER"
        row = "  " + f"{field:<20}" + "".join(f"{c:<{col_w}}" for c in cells) + agree
        print(row)


# ─────────────────────────────────────────────
# 3. GROUND-TRUTH COMPARISON
# ─────────────────────────────────────────────


def compare_to_ground_truth(domain: str, llm_answer: dict,
                            ground_truth: dict) -> dict:
    """Field-by-field comparison of an LLM answer against manually researched
    ground truth. Prints "LLM said X, ground truth is Y, MATCH/MISMATCH" per
    field and returns a {field: bool} match map."""
    print("\n" + "=" * 70)
    print(f"GROUND-TRUTH COMPARISON — {domain}")
    print("=" * 70)

    matches: dict[str, bool] = {}
    for field in OWNERSHIP_FIELDS:
        llm_val = llm_answer.get(field, "<missing>")
        gt_val = ground_truth.get(field, "<not researched>")
        is_match = _field_key(field, llm_val) == _field_key(field, gt_val)
        matches[field] = is_match
        verdict = "MATCH   " if is_match else "MISMATCH"
        print(f"  [{verdict}] {field}")
        print(f"      LLM said:     {_fmt_field(field, llm_val)}")
        print(f"      ground truth: {_fmt_field(field, gt_val)}")

    score = sum(matches.values()) / len(OWNERSHIP_FIELDS)
    print(f"\n  >> Ground-truth match: {score:.2f} "
          f"({sum(matches.values())}/{len(OWNERSHIP_FIELDS)} fields)")
    return matches


# ─────────────────────────────────────────────
# SUMMARY + PERSISTENCE
# ─────────────────────────────────────────────


def _models_agree_on(per_model: dict, field: str) -> bool:
    """Do all (non-errored) models agree on a single field for a domain?"""
    keys = {
        _field_key(field, ans.get(field))
        for ans in per_model.values()
        if "_error" not in ans
    }
    return len(keys) <= 1


def print_summary_table(consistency_results: dict, cross_model_results: dict):
    """Final summary: domain, intra-model consistency, cross-model agreement, and
    a TRUST flag marking domains where the LLM should not be trusted (consistency
    below 0.8, or cross-model disagreement on owner or ownership_type)."""
    print("\n\n" + "#" * 78)
    print("# SUMMARY")
    print("#" * 78)
    header = f"  {'domain':<22}{'consistency':<14}{'models_agree':<16}{'flag':<8}"
    print(header)
    print("  " + "-" * 58)

    for domain in consistency_results:
        cons = consistency_results[domain]["consistency"]

        per_model = cross_model_results.get(domain, {})
        owner_agree = _models_agree_on(per_model, "owner") if per_model else True
        type_agree = _models_agree_on(per_model, "ownership_type") if per_model else True
        models_agree = owner_agree and type_agree

        # Untrustworthy if shaky intra-model OR models disagree on the two
        # fields that matter most for ClearFrame.
        distrust = (cons < 0.8) or (not models_agree)
        flag = "DISTRUST" if distrust else "ok"

        agree_str = "yes" if models_agree else "no (owner/type)"
        print(f"  {domain:<22}{cons:<14.2f}{agree_str:<16}{flag:<8}")


def save_results(payload: dict) -> str:
    """Save all raw responses to a timestamped JSON file under RESULTS_DIR so runs
    can be compared over time. Returns the file path."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(RESULTS_DIR, f"ownership_test_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"\n[saved] Raw results written to {path}")
    return path


# ─────────────────────────────────────────────
# TEST DOMAINS
# ─────────────────────────────────────────────

TEST_DOMAINS = [
    "nytimes.com",          # well-known, ownership well documented
    "washingtonpost.com",   # well-known, single owner
    "aljazeera.net",        # state-funded, well documented
    "euronews.com",         # ownership changed in recent years — good staleness test
    "channelnewsasia.com",  # state-linked, moderately documented
    "elfaro.net",           # small independent, weaker pretraining coverage
    "apublica.org",         # small independent, weaker pretraining coverage
    "africanews.com",       # subsidiary relationship, moderate documentation
    "premiumtimesng.com",   # regional, weaker coverage
    "proceso.com.mx",       # regional, weaker coverage
]


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────


def main(domains: list[str] | None = None, runs_per_domain: int = 5):
    domains = domains or TEST_DOMAINS

    consistency_results = test_ownership_consistency(
        domains, runs_per_domain=runs_per_domain, model_label="gpt-4o"
    )
    cross_model_results = test_across_models(domains)

    # Ground-truth comparison for any domains that have been researched.
    gt_matches: dict[str, dict] = {}
    for domain in domains:
        if domain in GROUND_TRUTH:
            # Compare the first cross-model answer (gpt-4o) against ground truth.
            llm_answer = cross_model_results[domain].get("gpt-4o", {})
            gt_matches[domain] = compare_to_ground_truth(
                domain, llm_answer, GROUND_TRUTH[domain]
            )

    print_summary_table(consistency_results, cross_model_results)

    save_results({
        "generated_at": datetime.datetime.now().isoformat(),
        "runs_per_domain": runs_per_domain,
        "models": {k: v["model"] for k, v in MODELS.items()},
        "consistency": consistency_results,
        "cross_model": cross_model_results,
        "ground_truth_matches": gt_matches,
    })


if __name__ == "__main__":
    main()
