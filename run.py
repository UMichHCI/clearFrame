"""
ClearFrame Pipeline — v4
=========================
Architecture:
  Stage 1  — BrowserUse fetches and reads the base article via a real browser
             (handles JS-heavy sites, anti-bot headers, paywalled previews)
  Stage 2  — LLM builds a structured GDELT query plan (location, country, terms, timespan)
  Stage 3  — GDELT DOC API returns up to 50 candidate articles matching the query
  Stage 4  — MediaRank backend source quality filter (top 30% cutoff, never shown to users)
  Stage 5  — Article classification: LLM classifies the base article type
             (breaking news / ongoing situation / economics-policy /
              historical-contextual / human-interest)
  Stage 6  — Relevance judgment: LLM decides relevance holistically using guiding questions
  Stage 7  — Select top 5 by confidence, local perspective preferred
  Stage 8  — BrowserUse fetches full text of each selected article via a real browser,
             then LLM runs a structured comparison against the base article
  Stage 9  — Display results

What changed from v4 (trafilatura) to v4-browser (BrowserUse):
  - Stage 1: trafilatura + requests replaced by BrowserUse Agent
    → handles JS-rendered pages, anti-bot headers, SPA sites, soft paywalls
  - Stage 8: trafilatura loop replaced by BrowserUse Agent per article
    → same benefits — each candidate article is read by a real browser
  - Pipeline is now fully async (required by BrowserUse)
  - trafilatura and requests are removed as dependencies

Install:
  pip install browser-use openai pandas python-dotenv
  playwright install chromium

.env:
  OPENAI_API_KEY=your-key

Sources:
  - ClearFrame paper (Ayyob et al., 2025)
  - BrowserUse: https://github.com/browser-use/browser-use
  - GDELT 2.0: https://blog.gdeltproject.org/gdelt-2-0-our-global-world-in-realtime/
  - MediaRank: Ye & Skiena, KDD 2019 (arxiv.org/abs/1903.07581)
  - Munson & Resnick, CHI 2010 (doi:10.1145/1753326.1753543)
"""

import asyncio
import json
import os
import csv
import re
import time
from urllib.parse import urlparse

import requests       # still used for GDELT API only
import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI, RateLimitError
from langchain_openai import ChatOpenAI
from browser_use import Agent, Browser

load_dotenv()

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

MODEL_MINI   = "gpt-4o-mini"   # lightweight tasks: extraction, query plan, classification
MODEL_FULL   = "gpt-4o"        # heavier tasks: relevance checklist, full-text comparison

GDELT_URL    = "https://api.gdeltproject.org/api/v2/doc/doc"

# MediaRank: rank out of 50,695 sources. Top 30% = rank ≤ 15,208.
# Backend filter only — never shown to users.
MEDIARANK_TOTAL   = 50_695
MEDIARANK_CUTOFF  = int(MEDIARANK_TOTAL * 0.30)   # 15,208

MAX_GDELT_RESULTS    = 50    # max articles fetched from GDELT
MAX_CANDIDATES_RANK  = 20    # max candidates passed to relevance scoring
MAX_DISPLAY          = 5     # max articles shown to user


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

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


def load_mediarank_data(filepath: str) -> dict[str, int]:
    """
    Loads MediaRank domain → rank from a local CSV.
    Export from: https://www.media-rank.com/filter#
    Expected columns: domain, rank
    Returns empty dict if file not found (filter is then skipped).
    """
    ranks: dict[str, int] = {}
    if not os.path.exists(filepath):
        print(f"[WARNING] MediaRank file not found at '{filepath}'. Filter skipped.")
        return ranks
    with open(filepath, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            domain = row.get("domain", "").lower().strip()
            rank   = row.get("rank")
            if domain and rank:
                try:
                    ranks[domain] = int(rank)
                except ValueError:
                    pass
    print(f"[INFO] Loaded {len(ranks)} MediaRank ranks from '{filepath}'.")
    return ranks


# ─────────────────────────────────────────────
# STAGE 1 — FETCH BASE ARTICLE (BrowserUse)
# ─────────────────────────────────────────────
#
# Uses a real Chromium browser controlled by BrowserUse to load the page
# and extract the article text. This handles:
#   - JS-heavy / SPA sites that require JavaScript to render content
#   - Anti-bot headers that block simple HTTP requests
#   - Soft paywalls that show a preview before a login wall
#   - Sites that require cookies or session state
#
# BrowserUse runs a Playwright-controlled Chromium instance. The Agent is
# given a specific task: navigate to the URL and return the article text.
# The result comes back via history.final_result().
# ─────────────────────────────────────────────

async def get_article_text_browser(url: str) -> str:
    """
    Fetches and extracts article text using a real browser via BrowserUse.
    Falls back to an empty string if the browser fails or returns no content.

    The agent task is deliberately narrow — navigate and extract text only.
    max_steps=15 is sufficient for a simple article read; no interaction needed.
    """
    try:
        browser = Browser()
        llm     = ChatOpenAI(model=MODEL_MINI)

        agent = Agent(
            task=(
                f"Go to this URL: {url}\n"
                "Wait for the page to fully load, then extract and return the full "
                "main article text. Include the headline, byline, and all body paragraphs. "
                "Do not include navigation menus, ads, comments, or related article links. "
                "Return only the article text as plain text."
            ),
            llm=llm,
            browser=browser,
            max_steps=15
        )

        history = await agent.run()
        result  = history.final_result() or ""
        await browser.close()

        text = result.strip()
        if not text:
            print(f"  [WARNING] BrowserUse returned empty content for: {url}")
        return text[:8000]

    except Exception as e:
        print(f"  [WARNING] BrowserUse failed for {url}: {e}")
        return ""


# ─────────────────────────────────────────────
# STAGE 2 — GDELT QUERY PLAN
# ─────────────────────────────────────────────

QUERY_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "location":       {"type": "string"},
        "source_country": {"type": "string"},
        "terms": {
            "type":     "array",
            "items":    {"type": "string"},
            "minItems": 3,
            "maxItems": 4
        },
        "timespan": {
            "type": "string",
            "enum": ["1m", "3m", "6m", "1y"]
        }
    },
    "required":             ["location", "source_country", "terms", "timespan"],
    "additionalProperties": False
}

QUERY_PLAN_SYSTEM = """
You create ONE broad GDELT query plan for finding similar news articles.

Rules:
- Return exactly one location where the event takes place
- Return exactly one source_country (the country where the event takes place)
- If location is a city or region, source_country is the country containing it
- The location must always appear in the final query
- Return 3 to 4 broad topic terms — short, simple, broad recall over narrow precision
- Default timespan to 1y unless the article is clearly very time-bound (then 3m or 6m)
"""

def make_query_plan(article_text: str, client: OpenAI) -> dict:
    raw = api_chat(
        client,
        system=QUERY_PLAN_SYSTEM,
        user=f"Article:\n{article_text}",
        max_tokens=400,
        response_format={"type": "json_object"}
    )
    return json.loads(extract_json(raw))


def quote_if_needed(text: str) -> str:
    text = str(text).strip()
    return f'"{text}"' if " " in text else text


def normalize_country(text: str) -> str:
    return str(text).strip().lower().replace(" ", "")


def clean_plan(plan: dict, max_terms: int = 4) -> dict:
    location       = str(plan.get("location", "")).strip()
    source_country = str(plan.get("source_country", "")).strip()
    timespan       = str(plan.get("timespan", "1y")).strip()

    terms = []
    for term in plan.get("terms", []):
        term = str(term).strip()
        if (term
                and term.lower() != location.lower()
                and term.lower() != source_country.lower()
                and term not in terms):
            terms.append(term)
    terms = terms[:max_terms]

    if not location:
        raise ValueError("Query plan: location is empty.")
    if not source_country:
        raise ValueError("Query plan: source_country is empty.")
    if not terms:
        raise ValueError("Query plan: no usable terms.")

    return {"location": location, "source_country": source_country,
            "terms": terms, "timespan": timespan}


def build_gdelt_query(location: str, terms: list[str], source_country: str) -> str:
    """
    Builds a GDELT DOC API query string.
    Format: "LOCATION" AND (term1 OR term2 OR term3) AND sourcecountry:country
    """
    loc    = quote_if_needed(location)
    tparts = " OR ".join(quote_if_needed(t) for t in terms)
    ctry   = normalize_country(source_country)
    return f"{loc} AND ({tparts}) AND sourcecountry:{ctry}"


# ─────────────────────────────────────────────
# STAGE 3 — GDELT SEARCH
# ─────────────────────────────────────────────

def search_gdelt(query: str, timespan: str = "1y", maxrecords: int = 50) -> dict:
    """
    Queries the GDELT DOC API v2 and returns the raw JSON response.
    GDELT monitors broadcast, print, and web news in 100+ languages globally.
    Docs: https://blog.gdeltproject.org/gdelt-2-0-our-global-world-in-realtime/
    """
    params = {
        "query":      query,
        "mode":       "ArtList",
        "format":     "json",
        "maxrecords": maxrecords,
        "timespan":   timespan
    }
    response = requests.get(GDELT_URL, params=params, timeout=30)
    try:
        return response.json()
    except Exception:
        print("[WARNING] GDELT did not return valid JSON:")
        print(response.text[:500])
        return {}


# ─────────────────────────────────────────────
# STAGE 4 — MEDIARANK SOURCE QUALITY FILTER
# ─────────────────────────────────────────────

def filter_by_mediarank(df: pd.DataFrame, mediarank_lookup: dict[str, int]) -> tuple[pd.DataFrame, list[dict]]:
    """
    Applies the MediaRank top-30% cutoff as a backend hard gate.
    Sources outside the top 30% (rank > 15,208) are dropped.
    Sources with no rank data are allowed through.
    Results never shown to users.
    """
    if df.empty or not mediarank_lookup:
        return df, []

    passing    = []
    rejections = []

    for _, row in df.iterrows():
        domain = str(row.get("domain", "")).lower().strip()
        rank   = mediarank_lookup.get(domain)

        if rank is not None and rank > MEDIARANK_CUTOFF:
            rejections.append({
                "domain": domain,
                "rank":   rank,
                "reason": f"MediaRank rank {rank} is outside top 30% (>{MEDIARANK_CUTOFF}/{MEDIARANK_TOTAL})."
            })
        else:
            passing.append(row)

    passing_df = pd.DataFrame(passing).reset_index(drop=True) if passing else pd.DataFrame()
    return passing_df, rejections


# ─────────────────────────────────────────────
# STAGE 5 — ARTICLE TYPE CLASSIFICATION
# ─────────────────────────────────────────────
#
# The base article is classified before relevance scoring so the
# checklist questions adapt to the article type. This prevents the
# pipeline from being limited to only incident/breaking-news articles.
#
# Classification checklist (C1–C6) — all answers stored, nothing is a black box.
# ─────────────────────────────────────────────

CLASSIFICATION_SYSTEM = """
You are classifying a news article to understand what kind of story it is.
Use your own judgment. Return ONLY valid JSON. No preamble, no markdown fences.

Your goal is to identify the primary nature of the article so that relevance
scoring later can be interpreted appropriately. This is not a rigid test —
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
  - Is the focus on data, policy, and institutions — or on people and lived experience?
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


# ─────────────────────────────────────────────
# STAGE 6 — RELEVANCE SCORING
# ─────────────────────────────────────────────
#
# The LLM makes a holistic relevance judgment for each candidate.
# The questions below are a thinking guide — they are not a checklist
# to fill out mechanically. The LLM uses them to structure its reasoning,
# but the final decision is its own judgment call.
#
# The article type from Stage 5 tells the LLM what kind of relevance matters.
# ─────────────────────────────────────────────

RELEVANCE_SYSTEM_TEMPLATE = """
You are deciding whether candidate news articles are relevant to a base article.
The base article has been classified as: {primary_type}{secondary_note}.

Your job is to make a judgment call for each candidate — not to fill out a form.
Think through what relevance means for this type of article, then decide.

To help structure your thinking, consider questions like these:
  - Does this candidate cover the same subject as the base article, given what kind of story it is?
  - Is it about the same place, or a clearly related one?
  - Is it from a timeframe that makes it meaningfully relevant?
  - Does it add something — a different angle, local context, a contrasting framing?
  - Are the key actors, institutions, or communities involved overlapping?
  - Is this from a local outlet that might offer ground-level perspective?

These questions are not a checklist. They are examples of the kinds of things
that make an article relevant or irrelevant. Use your judgment. Some candidates
will be obviously relevant or obviously not — trust that. Others will be borderline;
in those cases, lean toward including if the article adds meaningful local perspective.

What to return for each candidate:
  - relevant: true or false — your overall judgment
  - confidence: "high", "medium", or "low" — how certain you are
  - reasoning: 2-3 sentences explaining your thinking in plain language
  - local_perspective: true or false — whether this adds a locally-grounded viewpoint

Return ONLY a valid JSON array. No preamble, no markdown fences.

Each item:
{{
  "row_index":        <integer matching the candidate's row_index>,
  "relevant":         true | false,
  "confidence":       "high" | "medium" | "low",
  "reasoning":        "<2-3 sentences of plain-language explanation>",
  "local_perspective": true | false
}}
"""

def score_candidates(base_text: str, candidates_df: pd.DataFrame,
                     classification: dict, client: OpenAI) -> list[dict]:
    """
    Makes a holistic relevance judgment for each candidate.
    The LLM uses the article type and a set of guiding questions to reason
    through relevance, then returns a plain-language explanation and a
    true/false decision. No rigid checklist — judgment-based.
    """
    if candidates_df.empty:
        return []

    primary_type   = classification.get("primary_type", "breaking_news")
    secondary      = classification.get("secondary_type")
    secondary_note = f" (secondary type: {secondary})" if secondary else ""

    system = RELEVANCE_SYSTEM_TEMPLATE.format(
        primary_type=primary_type,
        secondary_note=secondary_note
    )

    candidates_payload = []
    for i, (_, row) in enumerate(candidates_df.iterrows()):
        candidates_payload.append({
            "row_index":     i,
            "title":         str(row.get("title", "")),
            "domain":        str(row.get("domain", "")),
            "sourcecountry": str(row.get("sourcecountry", "")),
            "seendate":      str(row.get("seendate", "")),
            "language":      str(row.get("language", ""))
        })

    user_prompt = json.dumps({
        "base_article_summary": base_text[:3000],
        "candidates":           candidates_payload
    }, ensure_ascii=False)

    raw = api_chat(
        client,
        system=system,
        user=user_prompt,
        max_tokens=4000,
        model=MODEL_FULL
    )

    return json.loads(extract_json(raw))


# ─────────────────────────────────────────────
# STAGE 7 — SELECT TOP 5
# ─────────────────────────────────────────────

def select_top_articles(candidates_df: pd.DataFrame, scored: list[dict],
                        max_count: int = MAX_DISPLAY) -> pd.DataFrame:
    """
    Selects up to max_count articles from those the LLM judged as relevant.

    Selection logic:
      1. Keep only candidates where relevant = true
      2. Sort by confidence: high > medium > low
      3. Tiebreaker: prefer local_perspective = true
      4. Return top max_count

    Reasoning and confidence are preserved in the output DataFrame
    so the decision is fully inspectable.
    """
    confidence_rank = {"high": 3, "medium": 2, "low": 1}

    passing = [r for r in scored if r.get("relevant", False)]

    passing.sort(
        key=lambda r: (
            confidence_rank.get(r.get("confidence", "low"), 0),
            1 if r.get("local_perspective", False) else 0
        ),
        reverse=True
    )

    top = passing[:max_count]

    if not top:
        return pd.DataFrame()

    selected_indices = [r["row_index"] for r in top]
    selected_df      = candidates_df.iloc[selected_indices].copy().reset_index(drop=True)

    # Attach reasoning columns for full transparency
    meta_rows = []
    for r in top:
        meta_rows.append({
            "row_index":        r["row_index"],
            "relevant":         r.get("relevant", False),
            "confidence":       r.get("confidence", ""),
            "reasoning":        r.get("reasoning", ""),
            "local_perspective": r.get("local_perspective", False)
        })

    meta_df = pd.DataFrame(meta_rows).reset_index(drop=True)
    return pd.concat([selected_df, meta_df.drop(columns=["row_index"])], axis=1)


# ─────────────────────────────────────────────
# STAGE 8 — FULL-TEXT COMPARISON (BrowserUse)
# ─────────────────────────────────────────────
#
# For each of the top 5 selected articles, BrowserUse opens a real browser,
# loads the article URL, and extracts the full text — exactly the same way
# Stage 1 reads the base article. This solves the same problem: many local
# news sites in Mexico, Nigeria, Ukraine etc. are JS-rendered or have headers
# that block trafilatura/requests.
#
# Articles are fetched sequentially (not in parallel) to avoid launching
# multiple Chromium instances at once, which is memory-intensive.
# Each browser instance is opened and closed per article.
# ─────────────────────────────────────────────

FULLTEXT_COMPARISON_SCHEMA = {
    "type": "object",
    "properties": {
        "comparisons": {
            "type":  "array",
            "items": {
                "type": "object",
                "properties": {
                    "row_index":                 {"type": "integer"},
                    "summary":                   {"type": "string"},
                    "similarities":              {"type": "array", "items": {"type": "string"}},
                    "differences":               {"type": "array", "items": {"type": "string"}},
                    "source_country_perspective":{"type": "string"},
                    "added_value":               {"type": "string"},
                    "overall_relatedness": {
                        "type": "string",
                        "enum": ["very high", "high", "medium", "low"]
                    }
                },
                "required": ["row_index", "summary", "similarities", "differences",
                             "source_country_perspective", "added_value", "overall_relatedness"],
                "additionalProperties": False
            }
        }
    },
    "required":             ["comparisons"],
    "additionalProperties": False
}

FULLTEXT_COMPARISON_SYSTEM = """
You are comparing full news articles against an original article.

For each candidate:
- Explain how it is similar to and different from the original article
- Use the article text, not just the title
- Focus on: event overlap, geography, actors, timeline, framing, emphasis
- Explain what perspective the source country may add
- Infer perspective cautiously and only from article text, title, and metadata
- If perspective is unclear, say so
- Return one comparison object per candidate
"""

async def compare_full_text(original_text: str, top_df: pd.DataFrame, client: OpenAI) -> pd.DataFrame:
    """
    For each selected article, BrowserUse opens a real browser to fetch the full text,
    then the LLM compares each article against the base article.

    BrowserUse is used here for the same reason as Stage 1 — local news sites
    in the event country frequently block simple HTTP scrapers.

    Articles are fetched one at a time to avoid memory issues from multiple
    simultaneous Chromium instances.
    """
    if top_df.empty:
        return pd.DataFrame()

    top_df = top_df.copy()

    # Fetch full text for each candidate using BrowserUse
    article_texts = []
    for i, (_, row) in enumerate(top_df.iterrows()):
        url   = str(row.get("url", ""))
        title = str(row.get("title", ""))
        print(f"      [{i+1}/{len(top_df)}] Fetching: {title[:60]}...")
        text  = await get_article_text_browser(url)
        article_texts.append(text)
        if not text:
            print(f"        → No content retrieved. Comparison will use title/metadata only.")

    top_df["article_text"] = article_texts

    # Build comparison payload for the LLM
    candidates = []
    for i, (_, row) in enumerate(top_df.iterrows()):
        candidates.append({
            "row_index":     i,
            "title":         str(row.get("title", "")),
            "domain":        str(row.get("domain", "")),
            "language":      str(row.get("language", "")),
            "sourcecountry": str(row.get("sourcecountry", "")),
            "seendate":      str(row.get("seendate", "")),
            "article_text":  str(row.get("article_text", ""))[:6000]
        })
        })

    user_prompt = json.dumps({
        "original_article_text": original_text[:6000],
        "candidates":            candidates
    }, ensure_ascii=False)

    resp = client.chat.completions.create(
        model=MODEL_FULL,
        messages=[
            {"role": "system", "content": FULLTEXT_COMPARISON_SYSTEM},
            {"role": "user",   "content": user_prompt}
        ],
        max_tokens=4000,
        response_format={"type": "json_object"}
    )

    raw             = resp.choices[0].message.content.strip()
    comparison_data = json.loads(extract_json(raw)).get("comparisons", [])
    comparison_df   = pd.DataFrame(comparison_data)

    merged = comparison_df.merge(
        top_df.reset_index(drop=True).reset_index().rename(columns={"index": "row_index"}),
        on="row_index",
        how="left"
    )
    return merged


# ─────────────────────────────────────────────
# DISPLAY HELPERS
# ─────────────────────────────────────────────

def print_results(comparison_df: pd.DataFrame, n: int = MAX_DISPLAY):
    if comparison_df.empty:
        print("No results to display.")
        return

    for i, (_, row) in enumerate(comparison_df.head(n).iterrows(), start=1):
        title          = row.get("title", "N/A")
        url            = row.get("url", "")
        source         = row.get("sourcecountry", "N/A")
        domain         = row.get("domain", "N/A")
        language       = row.get("language", "N/A")
        relatedness    = row.get("overall_relatedness", "N/A")
        confidence     = row.get("confidence", "N/A")
        local          = row.get("local_perspective", False)
        reasoning      = row.get("reasoning", "")
        summary        = row.get("summary", "")
        similarities   = row.get("similarities", [])
        differences    = row.get("differences", [])
        perspective    = row.get("source_country_perspective", "")
        added_value    = row.get("added_value", "")

        print(f"\n{'='*70}")
        print(f"  #{i}  {title}")
        print(f"  URL             : {url}")
        print(f"  Source          : {source} | Domain: {domain} | Language: {language}")
        print(f"  Confidence      : {confidence} | Local perspective: {local}")
        print(f"  Overall related : {relatedness}")
        print(f"\n  RELEVANCE REASONING:\n  {reasoning}")
        print(f"\n  SUMMARY:\n  {summary}")
        print(f"\n  SIMILARITIES:")
        for s in similarities:
            print(f"    • {s}")
        print(f"\n  DIFFERENCES:")
        for d in differences:
            print(f"    • {d}")
        print(f"\n  SOURCE-COUNTRY PERSPECTIVE:\n  {perspective}")
        print(f"\n  ADDED VALUE:\n  {added_value}")

    print(f"\n{'='*70}")


# ─────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────

async def run_clearframe_pipeline(
    source_url: str,
    mediarank_filepath: str = "data/mediarank_rankings.csv",
    api_key: str | None = None,
    max_gdelt_results: int = MAX_GDELT_RESULTS,
    max_candidates_rank: int = MAX_CANDIDATES_RANK,
    top_n: int = MAX_DISPLAY
) -> dict:
    """
    Full ClearFrame pipeline (v4 — BrowserUse edition).

    Provide a URL. The pipeline does the rest.

    Stages:
      1  BrowserUse fetches the base article via a real Chromium browser
      2  LLM builds a structured GDELT query plan
      3  GDELT returns candidate articles
      4  MediaRank backend filter (top 30% cutoff, silent)
      5  LLM classifies the base article type
      6  LLM makes a holistic relevance judgment for each candidate
      7  Select top 5 by confidence, local perspective preferred
      8  BrowserUse fetches full text of each selected article, LLM compares
      9  Print and return results

    Args:
        source_url          : URL of the article the user is reading
        mediarank_filepath  : Path to MediaRank CSV (optional, skipped if missing)
        api_key             : OpenAI API key (falls back to OPENAI_API_KEY env var)
        max_gdelt_results   : How many articles to pull from GDELT (default 50)
        max_candidates_rank : How many to pass to relevance scoring (default 20)
        top_n               : How many to show to the user (default 5)

    Returns:
        dict with all intermediate and final outputs for debugging
    """
    client = OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))

    # ── Stage 1: Fetch base article via BrowserUse ────────────────────────
    print("\n[1/8] Fetching base article via BrowserUse...")
    article_text = await get_article_text_browser(source_url)
    if not article_text:
        raise ValueError(f"BrowserUse could not extract text from: {source_url}")
    print(f"      Extracted {len(article_text)} characters.")
    print(f"      Preview: {article_text[:200]}...\n")

    # ── Stage 2: Build GDELT query plan ───────────────────────────────────
    print("[2/8] Building GDELT query plan...")
    plan  = make_query_plan(article_text, client)
    plan  = clean_plan(plan, max_terms=4)
    query = build_gdelt_query(plan["location"], plan["terms"], plan["source_country"])
    print(f"      Plan     : {plan}")
    print(f"      Query    : {query}")

    # ── Stage 3: Search GDELT ─────────────────────────────────────────────
    print(f"\n[3/8] Searching GDELT (timespan={plan['timespan']}, max={max_gdelt_results})...")
    gdelt_results = search_gdelt(query, timespan=plan["timespan"], maxrecords=max_gdelt_results)
    gdelt_df      = pd.DataFrame(gdelt_results.get("articles", []))
    print(f"      GDELT returned {len(gdelt_df)} articles.")

    if gdelt_df.empty:
        print("      No results from GDELT. Exiting early.")
        return {"source_url": source_url, "article_text": article_text,
                "plan": plan, "query": query, "gdelt_df": gdelt_df,
                "selected_df": pd.DataFrame(), "comparison_df": pd.DataFrame()}

    # ── Stage 4: MediaRank filter ─────────────────────────────────────────
    print(f"\n[4/8] Applying MediaRank source quality filter...")
    mediarank_lookup         = load_mediarank_data(mediarank_filepath)
    filtered_df, rejections  = filter_by_mediarank(gdelt_df, mediarank_lookup)
    print(f"      {len(filtered_df)} passed  |  {len(rejections)} rejected")
    for r in rejections:
        print(f"        ✗ {r['domain']} — {r['reason']}")

    candidates_df = filtered_df.head(max_candidates_rank).reset_index(drop=True)

    if candidates_df.empty:
        print("      No candidates after filtering. Exiting early.")
        return {"source_url": source_url, "article_text": article_text,
                "plan": plan, "query": query, "gdelt_df": gdelt_df,
                "selected_df": pd.DataFrame(), "comparison_df": pd.DataFrame()}

    # ── Stage 5: Classify base article ───────────────────────────────────
    print(f"\n[5/8] Classifying base article type...")
    classification = classify_article(article_text, client)
    print(f"      Primary type : {classification.get('primary_type')}")
    print(f"      Secondary    : {classification.get('secondary_type')}")
    print(f"      Justification: {classification.get('justification')}")

    # ── Stage 6: Relevance scoring ────────────────────────────────────────
    print(f"\n[6/8] Judging relevance of {len(candidates_df)} candidates...")
    scored = score_candidates(article_text, candidates_df, classification, client)

    passed = sum(1 for r in scored if r.get("relevant", False))
    print(f"      {passed} candidates judged relevant out of {len(scored)}")

    for r in scored:
        status     = "RELEVANT" if r.get("relevant", False) else "NOT RELEVANT"
        confidence = r.get("confidence", "")
        print(f"        [{status}] row {r['row_index']}  confidence: {confidence}")

    # ── Stage 7: Select top articles ─────────────────────────────────────
    print(f"\n[7/8] Selecting top {top_n} articles...")
    selected_df = select_top_articles(candidates_df, scored, max_count=top_n)
    print(f"      {len(selected_df)} article(s) selected.")

    if selected_df.empty:
        print("      No articles passed selection criteria.")
        return {"source_url": source_url, "article_text": article_text,
                "plan": plan, "query": query, "gdelt_df": gdelt_df,
                "classification": classification, "scored": scored,
                "selected_df": pd.DataFrame(), "comparison_df": pd.DataFrame()}

    # ── Stage 8: Full-text comparison via BrowserUse ─────────────────────
    print(f"\n[8/8] Fetching full text via BrowserUse and comparing top {len(selected_df)} articles...")
    comparison_df = await compare_full_text(article_text, selected_df, client)
    print(f"      Comparison complete for {len(comparison_df)} article(s).")

    # ── Stage 9: Display ─────────────────────────────────────────────────
    print_results(comparison_df, n=top_n)

    return {
        "source_url":      source_url,
        "article_text":    article_text,
        "plan":            plan,
        "query":           query,
        "gdelt_df":        gdelt_df,
        "classification":  classification,
        "scored":          scored,
        "selected_df":     selected_df,
        "comparison_df":   comparison_df
    }


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":

    # Swap any of these in to test different article types
    SOURCE_URL = "https://www.cbsnews.com/news/missing-workers-canada-mining-company-found-dead-sinaloa-mexico/"
    # SOURCE_URL = "https://www.washingtonpost.com/world/2026/03/17/us-iran-israel-war-ali-larijani/"
    # SOURCE_URL = "https://www.aljazeera.com/news/2026/3/17/many-killed-wounded-after-blasts-hit-nigerias-maiduguri-witnesses-say"
    # SOURCE_URL = "https://www.who.int/news/item/09-01-2026-sudan-1000-days-of-war-deepen-the-world-s-worst-health-and-humanitarian-crisis"
    # SOURCE_URL = "https://www.nbcnews.com/world/north-korea/north-korea-fires-missiles-sea-show-force-seoul-rcna263450"
    # SOURCE_URL = "https://www.cbc.ca/news/world/venezuela-us-influence-trump-9.7122944"
    # SOURCE_URL = "https://www.nytimes.com/2026/03/14/business/media/washington-post-jeff-bezos-layoffs.html"

    output = asyncio.run(run_clearframe_pipeline(
        source_url=SOURCE_URL,
        mediarank_filepath="data/mediarank_rankings.csv"  # optional — skipped if not present
    ))