"""
ClearFrame Pipeline — v5
=========================
Article selection and analysis are grounded exclusively in the propaganda model
of Herman and Chomsky (Manufacturing Consent, 1988). Candidates are selected by
full-text pair analysis against the base article, not by title-based scoring.

The propaganda model is STRUCTURAL, not conspiratorial. Coverage patterns follow
from an outlet's position, its audience, its sourcing constraints, and the
institutional pressures it operates under. No editorial directive is required for
these patterns to appear — the selection happens upstream of any individual
article. Nothing in this pipeline attributes intent to journalists or outlets,
and no user-facing string may do so.

Architecture:
  Stage 1  — trafilatura fetches and extracts the base article text + pub date
  Stage 2  — LLM builds a structured GDELT query plan (location, country, terms, timespan)
  Stage 3  — GDELT DOC API returns candidate articles (+ regional fallback)
  Stage 4  — Article classification: LLM classifies the base article type
             (breaking news / ongoing situation / economics-policy /
              historical-contextual / human-interest)
  Stage 5  — Topical gate: lightweight binary same-event filter on title/metadata
  Stage 6  — Full-text fetch for up to 10 gated candidates, local sources first
  Stage 7  — Chomsky pair analysis: base <-> candidate, full text, per-category findings
  Stage 8  — Selection: deterministic illumination score computed in Python, top 5
  Stage 9  — Synthesis + display (brief user-facing output, verbose dev output)

Install:
  pip install trafilatura openai pandas python-dotenv requests

.env:
  OPENAI_API_KEY=your-key

Sources:
  - ClearFrame paper (Ayyob et al., 2025)
  - Herman & Chomsky, Manufacturing Consent (1988)
  - trafilatura: https://trafilatura.readthedocs.io/
  - GDELT 2.0: https://blog.gdeltproject.org/gdelt-2-0-our-global-world-in-realtime/
  - Munson & Resnick, CHI 2010 (doi:10.1145/1753326.1753543)
"""

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests
import trafilatura
import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI, RateLimitError

load_dotenv()

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

MODEL_MINI   = "gpt-4o-mini"   # lightweight tasks: query plan, classification, topical gate
MODEL_FULL   = "gpt-4o"        # heavier tasks: outlet context, pair analysis, synthesis

GDELT_URL    = "https://api.gdeltproject.org/api/v2/doc/doc"

MAX_GDELT_RESULTS       = 50    # max articles fetched from GDELT
MAX_CANDIDATES_RANK     = 20    # max candidates passed to the topical gate
MAX_FULLTEXT_CANDIDATES = 10    # max gated candidates we fetch full text for
MAX_DISPLAY             = 5     # max articles shown to user

DEBUG_DUMP_DIR = "debug_runs"   # timestamped per-run JSON dumps, for prompt iteration

# Shown verbatim with every set of results. The propaganda model is structural;
# this line exists so no reader can take the findings as claims about intent.
STRUCTURAL_NOTE = (
    "These patterns reflect how news systems are structured — outlet position, "
    "audience, and sourcing — not the intent of individual journalists."
)

_gdelt_request_count = 0     # debug counter — tracks GDELT API calls this run

# ─────────────────────────────────────────────
# REGIONAL FALLBACK CONFIG
# ─────────────────────────────────────────────

GDELT_FALLBACK_THRESHOLD = 5   # trigger fallback if GDELT returns fewer than this many results

COUNTRY_FALLBACK: dict[str, str] = {
    # Middle East and North Africa → Al Jazeera
    "iraq":         "aljazeera.net",
    "syria":        "aljazeera.net",
    "iran":         "aljazeera.net",
    "yemen":        "aljazeera.net",
    "libya":        "aljazeera.net",
    "egypt":        "aljazeera.net",
    "saudi arabia": "aljazeera.net",
    "jordan":       "aljazeera.net",
    "lebanon":      "aljazeera.net",
    "palestine":    "aljazeera.net",
    "tunisia":      "aljazeera.net",
    "morocco":      "aljazeera.net",
    "algeria":      "aljazeera.net",
    "oman":         "aljazeera.net",
    # Africa → AllAfrica
    "nigeria":      "allafrica.com",
    "ethiopia":     "allafrica.com",
    "kenya":        "allafrica.com",
    "ghana":        "allafrica.com",
    "sudan":        "allafrica.com",
    "somalia":      "allafrica.com",
    "drc":          "allafrica.com",
    "tanzania":     "allafrica.com",
    "uganda":       "allafrica.com",
    "mozambique":   "allafrica.com",
    "zimbabwe":     "allafrica.com",
    "cameroon":     "allafrica.com",
    "senegal":      "allafrica.com",
    "mali":         "allafrica.com",
    "burkina faso": "allafrica.com",
    # Central America → El Faro
    "el salvador":  "elfaro.net",
    "guatemala":    "elfaro.net",
    "honduras":     "elfaro.net",
    "nicaragua":    "elfaro.net",
    "costa rica":   "elfaro.net",
    "panama":       "elfaro.net",
    "belize":       "elfaro.net",
    "mexico":       "elfaro.net",
    # South America → Agência Pública
    "colombia":     "apublica.org",
    "venezuela":    "apublica.org",
    "brazil":       "apublica.org",
    "argentina":    "apublica.org",
    "peru":         "apublica.org",
    "chile":        "apublica.org",
    "ecuador":      "apublica.org",
    "bolivia":      "apublica.org",
    "paraguay":     "apublica.org",
    "uruguay":      "apublica.org",
    "guyana":       "apublica.org",
    # Europe → Euronews
    "ukraine":      "euronews.com",
    "russia":       "euronews.com",
    "poland":       "euronews.com",
    "hungary":      "euronews.com",
    "serbia":       "euronews.com",
    "turkey":       "euronews.com",
    "greece":       "euronews.com",
    "romania":      "euronews.com",
    "belarus":      "euronews.com",
    "georgia":      "euronews.com",
    "albania":      "euronews.com",
    "kosovo":       "euronews.com",
    "moldova":      "euronews.com",
    # Asia → Channel News Asia
    "myanmar":      "channelnewsasia.com",
    "afghanistan":  "channelnewsasia.com",
    "pakistan":     "channelnewsasia.com",
    "bangladesh":   "channelnewsasia.com",
    "sri lanka":    "channelnewsasia.com",
    "thailand":     "channelnewsasia.com",
    "indonesia":    "channelnewsasia.com",
    "philippines":  "channelnewsasia.com",
    "north korea":  "channelnewsasia.com",
    "cambodia":     "channelnewsasia.com",
    "laos":         "channelnewsasia.com",
    "vietnam":      "channelnewsasia.com",
    "nepal":        "channelnewsasia.com",
}

FALLBACK_DEFAULT = "reuters.com"


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


# ─────────────────────────────────────────────
# STAGE 1 — FETCH BASE ARTICLE (trafilatura)
# ─────────────────────────────────────────────

_SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

def get_article_text(url: str) -> tuple[str, datetime]:
    """
    Fetches and extracts article text and publication date using trafilatura.
    Returns (text, pub_date). Falls back to ("", today) on failure.
    """
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        response = requests.get(url, headers=_SCRAPE_HEADERS, timeout=20)
        response.raise_for_status()
        html = response.text
        text = trafilatura.extract(html, include_comments=False, include_tables=False)
        if not text:
            print(f"  [WARNING] trafilatura returned empty content for: {url}")
            return "", today

        pub_date = today
        try:
            metadata = trafilatura.extract_metadata(html)
            if metadata and metadata.date:
                parsed = datetime.fromisoformat(metadata.date.split("T")[0])
                pub_date = parsed.replace(tzinfo=timezone.utc)
        except Exception:
            pass

        if pub_date == today:
            print(f"  [WARNING] No publication date found — defaulting to today.")
        else:
            print(f"      Publication date: {pub_date.strftime('%Y-%m-%d')}")

        return text[:8000], pub_date
    except Exception as e:
        print(f"  [WARNING] trafilatura failed for {url}: {e}")
        return "", today


# ─────────────────────────────────────────────
# STAGE 2 — GDELT QUERY PLAN
# ─────────────────────────────────────────────

QUERY_PLAN_SYSTEM = """
You create ONE broad GDELT query plan for finding similar news articles.
Respond with a JSON object only — no explanation, no markdown, no extra keys.

The JSON must have exactly these four top-level keys:
  "location"            — the city or region where the event takes place (string, never empty)
  "source_country"      — the country that contains that location (string, never empty)
  "terms"               — 3 to 4 short broad topic keywords (array of strings)
  "window_days_before"  — integer: how many days before the publication date to search
  "window_days_after"   — integer: how many days after the publication date to search

Choose window_days_before and window_days_after based on the article type:
  Breaking news          → 14 before, 14 after
  Ongoing situation      → 90 before, 90 after
  Historical/background  → 365 before, 180 after
  Economics/policy       → 180 before, 90 after
  Human interest         → 60 before, 60 after
  Uncertain              → 90 before, 90 after

Example output:
{
  "location": "Puerto Vallarta",
  "source_country": "Mexico",
  "terms": ["cartel", "violence", "drug war"],
  "window_days_before": 14,
  "window_days_after": 14
}

Rules:
- location and source_country must never be empty strings
- terms should be broad for high recall — avoid overly specific phrases
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
    location            = str(plan.get("location", "")).strip()
    source_country      = str(plan.get("source_country", "")).strip()
    window_days_before  = int(plan.get("window_days_before", 90))
    window_days_after   = int(plan.get("window_days_after", 90))

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
            "terms": terms, "window_days_before": window_days_before,
            "window_days_after": window_days_after}


def build_gdelt_query(
    location: str, terms: list[str], source_country: str,
    pub_date: datetime, window_days_before: int, window_days_after: int
) -> tuple[str, str, str]:
    """
    Builds a GDELT DOC API query string and the start/end datetime strings.
    Returns (query, startdatetime, enddatetime).
    GDELT datetime format: YYYYMMDDHHMMSS
    """
    today      = datetime.now(timezone.utc)
    start_date = pub_date - timedelta(days=window_days_before)
    end_date   = min(pub_date + timedelta(days=window_days_after), today)

    loc    = quote_if_needed(location)
    tparts = " OR ".join(quote_if_needed(t) for t in terms)
    ctry   = normalize_country(source_country)
    query  = f"{loc} AND ({tparts}) AND sourcecountry:{ctry}"

    start_str = start_date.strftime("%Y%m%d%H%M%S")
    end_str   = end_date.strftime("%Y%m%d%H%M%S")
    return query, start_str, end_str


# ─────────────────────────────────────────────
# REGIONAL FALLBACK HELPERS
# ─────────────────────────────────────────────

def get_fallback_domain(country: str) -> str:
    """Returns the regional fallback domain for a given country, or FALLBACK_DEFAULT."""
    return COUNTRY_FALLBACK.get(country.lower().strip(), FALLBACK_DEFAULT)


def search_gdelt_fallback(
    query_terms: str, fallback_domain: str,
    startdatetime: str, enddatetime: str,
    maxrecords: int = 50
) -> dict:
    """
    Runs a GDELT search replacing the sourcecountry filter with domain:fallback_domain.
    query_terms should be the location+terms portion of the query only — no sourcecountry clause.
    """
    fallback_query = f"{query_terms} AND domain:{fallback_domain}"
    return search_gdelt(fallback_query, startdatetime=startdatetime,
                        enddatetime=enddatetime, maxrecords=maxrecords)


# ─────────────────────────────────────────────
# STAGE 3 — GDELT SEARCH
# ─────────────────────────────────────────────

def search_gdelt(query: str, startdatetime: str, enddatetime: str, maxrecords: int = 50) -> dict:
    """
    Queries the GDELT DOC API v2 and returns the raw JSON response.
    GDELT monitors broadcast, print, and web news in 100+ languages globally.
    Docs: https://blog.gdeltproject.org/gdelt-2-0-our-global-world-in-realtime/
    """
    global _gdelt_request_count
    params = {
        "query":         query,
        "mode":          "ArtList",
        "format":        "json",
        "maxrecords":    maxrecords,
        "startdatetime": startdatetime,
        "enddatetime":   enddatetime,
    }
    _gdelt_request_count += 1
    full_url = requests.Request("GET", GDELT_URL, params=params).prepare().url
    print(f"  [DEBUG] GDELT request #{_gdelt_request_count}: {full_url}")

    # Flat 5s wait between every retry — both for rate limits (429) and for
    # request-level failures (read timeout, connection reset). GDELT is often
    # slow to hand off the connection, so a timed-out request is retried rather
    # than allowed to crash the pipeline. Fixed 5s keeps total wait bounded and
    # avoids the long tail of exponential backoff.
    RETRY_WAIT = 5
    response = None
    for attempt in range(5):
        try:
            response = requests.get(GDELT_URL, params=params, timeout=30)
        except requests.exceptions.RequestException as e:
            print(f"  [DEBUG] GDELT request failed ({e.__class__.__name__}) on attempt {attempt + 1}.")
            if attempt < 4:
                print(f"  [DEBUG] Waiting {RETRY_WAIT}s before retry...")
                time.sleep(RETRY_WAIT)
            continue

        print(f"  [DEBUG] GDELT HTTP status: {response.status_code} (attempt {attempt + 1})")
        if response.status_code != 429:
            break
        print(f"  [DEBUG] Rate limited — waiting {RETRY_WAIT}s before retry...")
        time.sleep(RETRY_WAIT)

    if response is None:
        print("  [WARNING] GDELT request failed on every attempt — returning no results.")
        return {}

    try:
        return response.json()
    except Exception:
        print("[WARNING] GDELT did not return valid JSON:")
        print(response.text[:500])
        return {}


# ─────────────────────────────────────────────
# STAGE 4 — ARTICLE TYPE CLASSIFICATION
# ─────────────────────────────────────────────
#
# The base article is classified before the topical gate so that "same event"
# is interpreted appropriately for the article type. This prevents the pipeline
# from being limited to only incident/breaking-news articles.
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
# STAGE 5 — TOPICAL GATE
# ─────────────────────────────────────────────
#
# Deliberately light. Its only job is filtering, not ranking.
#
# Nothing in the propaganda model can be read off a title. Register, voice,
# presupposition and suppressed alternatives all live in the body of an article,
# so this stage produces no scores of any kind — only a binary same-event
# judgment. Scoring happens in Stage 7, after full text is available.
# ─────────────────────────────────────────────

TOPICAL_GATE_SYSTEM = """
You are filtering candidate news articles against a base article. This is a filter,
not a ranking. Make one binary judgment per candidate and nothing more.

The base article has been classified as: {primary_type}{secondary_note}.

For each candidate, using only its title, domain, source country, date, and language,
decide: is this article about the same underlying event, situation, or subject as the
base article — interpreted appropriately for the base article's type?

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
text — only its title and metadata. Any judgment beyond "same subject or not" would be
unfounded here.

Coverage patterns in a news system are structural — they follow from an outlet's position,
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


def topical_gate(base_text: str, candidates_df: pd.DataFrame,
                 classification: dict, client: OpenAI) -> list[dict]:
    """
    Binary same-event filter over candidate titles/metadata. No scoring of any kind.
    Returns one dict per candidate: {row_index, topically_relevant, reason}.
    """
    if candidates_df.empty:
        return []

    primary_type   = classification.get("primary_type", "breaking_news")
    secondary      = classification.get("secondary_type")
    secondary_note = f" (secondary type: {secondary})" if secondary else ""

    system = TOPICAL_GATE_SYSTEM.format(
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
            "language":      str(row.get("language", "")),
        })

    user_prompt = json.dumps({
        "base_article_summary": base_text[:3000],
        "candidates":           candidates_payload,
    }, ensure_ascii=False)

    raw = api_chat(
        client,
        system=system,
        user=user_prompt,
        max_tokens=2000,
        model=MODEL_MINI,
        response_format={"type": "json_object"},
    )

    results = json.loads(extract_json(raw)).get("results", [])

    # A candidate the model returned no verdict for is excluded rather than
    # silently admitted — a missing verdict is not a passing verdict.
    seen = {r.get("row_index") for r in results}
    for i in range(len(candidates_df)):
        if i not in seen:
            results.append({
                "row_index":          i,
                "topically_relevant": False,
                "reason":             "No verdict returned by the topical gate.",
            })

    return sorted(results, key=lambda r: r.get("row_index", 0))


# ─────────────────────────────────────────────
# STAGE 6 — FULL-TEXT FETCH
# ─────────────────────────────────────────────
#
# Local sources are ordered first: an outlet reporting from inside the country
# where the event happened sits in a different structural position than a distant
# one, and pairs across that divide are the most likely to be illuminating.
# ─────────────────────────────────────────────

def fetch_candidate_texts(candidates_df: pd.DataFrame, gate_results: list[dict],
                          event_country: str,
                          max_candidates: int = MAX_FULLTEXT_CANDIDATES) -> pd.DataFrame:
    """
    Fetches full text for the candidates that passed the topical gate.

    Ordering: candidates whose sourcecountry matches the event country come first,
    then GDELT's original order. Full text is fetched sequentially for the first
    max_candidates. Candidates whose fetch returns empty text are dropped.

    Returns a DataFrame with an `article_text` column and a `row_index` column
    pointing back into candidates_df.
    """
    passed = [r["row_index"] for r in gate_results if r.get("topically_relevant")]
    if not passed or candidates_df.empty:
        return pd.DataFrame()

    event_ctry = normalize_country(event_country)

    def is_local(idx: int) -> bool:
        row = candidates_df.iloc[idx]
        return normalize_country(str(row.get("sourcecountry", ""))) == event_ctry

    # Stable sort: local sources first, GDELT order preserved within each group.
    ordered = sorted(passed, key=lambda idx: 0 if is_local(idx) else 1)
    n_local = sum(1 for idx in passed if is_local(idx))

    print(f"      {len(passed)} candidate(s) passed the gate "
          f"({n_local} local to {event_country}, {len(passed) - n_local} non-local).")
    print(f"      Fetching full text for up to {max_candidates}, local sources first.")

    to_fetch = ordered[:max_candidates]
    rows: list[dict] = []

    for n, idx in enumerate(to_fetch, start=1):
        row    = candidates_df.iloc[idx]
        url    = str(row.get("url", ""))
        title  = str(row.get("title", ""))
        domain = str(row.get("domain", ""))
        tag    = "local" if is_local(idx) else "non-local"

        print(f"      [{n}/{len(to_fetch)}] ({tag}) {domain} — {title[:55]}...")
        text, _pub_date = get_article_text(url)

        if not text or not text.strip():
            print("           -> dropped: no text retrieved.")
            continue

        record = row.to_dict()
        record["row_index"]    = idx
        record["article_text"] = text
        record["is_local"]     = is_local(idx)
        rows.append(record)
        print(f"           -> {len(text)} characters.")

    if not rows:
        print("      No candidate yielded usable full text.")
        return pd.DataFrame()

    print(f"      {len(rows)} candidate(s) have usable full text.")
    return pd.DataFrame(rows).reset_index(drop=True)


# ─────────────────────────────────────────────
# OUTLET CONTEXT — BACKEND ONLY
# ─────────────────────────────────────────────
#
# What the model recalls about an outlet's ownership is drawn from training data
# and may be wrong or out of date. It is used only to inform the pair analysis's
# reasoning about structural position. It is never asserted as fact in any output
# field, and it is never shown to users.
# ─────────────────────────────────────────────

_OUTLET_CONTEXT_CACHE: dict[str, dict] = {}   # domain -> context, for this run

OUTLET_CONTEXT_SYSTEM = """
You are asked what you know, from your training data, about the institutional position
of a news outlet: who owns it, how it is funded, and what its relationship is to state
power in the country it operates from.

Accuracy matters far more than completeness. If you are not confident, "unknown" is the
correct answer. Fabricating or guessing at ownership details is a failure. Do not infer
ownership from the outlet's name, from its country, or from the general reputation of
media in that country. If you do not specifically recall this outlet, say so.

Return ONLY valid JSON, no markdown fences:

{
  "ownership_summary":  "<who owns and funds it, or 'unknown'>",
  "state_relationship": "<state-owned | state-funded | state-aligned | independent of the state | adversarial to the state | unknown>",
  "confidence":         "high | medium | low"
}

Use confidence "low" whenever you are working from a general impression rather than
specific recall. Use "unknown" freely.

Describe the outlet's institutional position structurally — ownership, funding, and its
relationship to state power. Do not characterise the intent of the outlet or its journalists.
"""


def get_outlet_context(domain: str, client: OpenAI) -> dict:
    """
    Returns {ownership_summary, state_relationship, confidence} for a domain.
    Cached per domain for the lifetime of the run.
    BACKEND ONLY — must never reach a user-facing field.
    """
    key = str(domain).lower().strip()
    if key in _OUTLET_CONTEXT_CACHE:
        return _OUTLET_CONTEXT_CACHE[key]

    fallback = {
        "ownership_summary":  "unknown",
        "state_relationship": "unknown",
        "confidence":         "low",
    }
    if not key:
        return fallback

    try:
        raw = api_chat(
            client,
            system=OUTLET_CONTEXT_SYSTEM,
            user=f"News outlet domain: {key}",
            max_tokens=400,
            model=MODEL_FULL,
            response_format={"type": "json_object"},
        )
        parsed  = json.loads(extract_json(raw))
        context = {
            "ownership_summary":  str(parsed.get("ownership_summary", "unknown")),
            "state_relationship": str(parsed.get("state_relationship", "unknown")),
            "confidence":         str(parsed.get("confidence", "low")),
        }
    except Exception as e:
        print(f"      [WARNING] Outlet context lookup failed for {key}: {e}")
        context = fallback

    _OUTLET_CONTEXT_CACHE[key] = context
    return context


# ─────────────────────────────────────────────
# STAGE 7 — CHOMSKY PAIR ANALYSIS
# ─────────────────────────────────────────────
#
# The heart of the system: one full-text call per candidate, comparing it against
# the base article through the analytic categories of the propaganda model.
#
# Sponsor-congeniality of quoted experts is deliberately EXCLUDED from the
# categories below. Herman and Chomsky treat the funding of experts as part of the
# sourcing filter, but think-tank and expert funding is largely undisclosed: the
# model cannot reliably determine who funds a quoted analyst, so any finding in
# that category would rest on guesswork. It is left out rather than guessed at.
# ─────────────────────────────────────────────

CHOMSKY_CATEGORIES = [
    "worthy_unworthy_victims",
    "agency_attribution",
    "presuppositions_doctrine",
    "selective_criteria",
    "suppressed_alternative",
    "smoke_and_discrepancies",
]

CHOMSKY_PAIR_SYSTEM = """
You are comparing two news articles about the same event through the analytic categories
of Herman and Chomsky's propaganda model (Manufacturing Consent, 1988).

The model is STRUCTURAL, not conspiratorial. Coverage patterns arise from an outlet's
position, its audience, and its sourcing — not from the intent of journalists. No editorial
directive is required for these patterns to appear; the selection happens upstream of any
individual article. Never write that an outlet or a journalist "hid," "chose to suppress,"
"deliberately" did anything, or is "producing propaganda." Describe patterns as consequences
of structure. If you cannot state a finding without attributing intent, the finding is wrong
as stated — restate it structurally, or drop it.

Your job is to find what this PAIR of articles reveals that neither reveals alone.

The general analytic move underlying every category is the COUNTERFACTUAL SWAP: would these
facts have been written in this register if the actors' nationalities or alignments were
swapped? Would the same things be presupposed? Would the same evaluative criteria apply?

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ANTI-OVER-FINDING RULES — READ THESE BEFORE ANYTHING ELSE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"applies": false is a valid and EXPECTED answer.

Most article pairs will exhibit real evidence for only ONE TO THREE of the six categories.
Flagging many categories on weak evidence is a failure mode, not thoroughness.

Every "applies": true requires AT LEAST ONE VERBATIM QUOTE as evidence. If you cannot quote
it, it does not apply. Quotes must be copied exactly from the article text you were given —
never paraphrased, never reconstructed.

If the evidence is a stretch, mark the category not-applicable, or mark it low confidence.
A pair with one well-evidenced finding is a better result than a pair with six thin ones.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THE SIX CATEGORIES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. worthy_unworthy_victims
Compare how the two articles treat the people harmed. Worthy victims receive extensive
attention, vivid detail, expressions of indignation, and demands for justice. Unworthy
victims receive a low-key, philosophical register that treats violence as a sad constant of
the human condition — sober sadness doing the work that suppression would otherwise do.
Also check RESPONSIBILITY DIRECTION: for worthy victims, responsibility is traced upward to
leaders and policies; for unworthy victims it is pushed downward to rogue actors, local
conditions, or tragic excess.
Also check FACTS WITHOUT RECOGNITION: harm that is on the page but reported in a register
inappropriate to it — civilian deaths mentioned inside a paragraph about operational
outcomes, for instance. This is what defeats the defense of "but they reported it."

2. agency_attribution
Compare the causal grammar. When one article names a clear agent with active, unambiguous
language ("he slaughtered," "forces massacred") and the other renders comparable harm
agentless — passive voice ("were killed"), agentless nominalization ("a wave of violence"),
softened vocabulary — that asymmetry is the finding. The killing described as something that
happened rather than something someone did.

3. presuppositions_doctrine
Identify what each article stands on as axioms rather than as claims to be defended:
  - definite descriptions that settle contested questions in passing ("the rebels," "the regime")
  - verbs that assume a motive structure ("defending," "stabilizing," "responding")
  - modifiers that smuggle judgment ("legitimately elected," "controversial leader")
  - what is treated as needing explanation, versus what passes as common sense
  - whose quoted claims are absorbed into the article's own narration, versus held at arm's
    length as attributed claims
  - whether a mobilizing ideological enemy is invoked in ways that lower the standard of evidence
Where the two articles stand on different floors, name both floors.

4. selective_criteria
Identify what standards each article invites the reader to judge the event by, and whether the
chosen criteria are ones the event is positioned to pass. The classic case: an ally's election
judged by turnout and orderly polling stations, while the criteria that would be applied to an
adversary's election — whether the opposition could campaign safely, whether the press was
free, whether the preconditions for a meaningful vote obtained — stay off the page.
Where the two articles apply different criteria to the same event, name both sets.

5. suppressed_alternative
Ask whether there is a rival account of this event — one an informed observer outside the
reporting country's mainstream would recognize as plausible — that one article forecloses so
completely that the chosen frame reads as the only possible reading. The article does not argue
against the alternative; the alternative simply is not there, so the reader does not know there
is something to weigh.
CRITICALLY: the two articles in this pair can be each other's suppressed alternative. Check
both directions.

6. smoke_and_discrepancies
Two narrower checks combined.
  (a) ARTICLE-LEVEL SMOKE PRODUCTION: does either article accumulate volume around a frame —
      speculation, peripheral detail, expressions of doubt and interest — while never engaging
      the substantive questions (motive, quality of evidence) that would adjudicate it?
  (b) FACTUAL DISCREPANCIES: where do the two articles make incompatible factual claims
      (casualty counts, sequence of events, who initiated)? Flag the discrepancy WITHOUT
      adjudicating which is true — you cannot verify facts, only surface disagreement.
Where the facts AGREE across institutionally very different outlets, that agreement is itself
worth one sentence: it tells the reader the fact is solid.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONFIDENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Confidence is defined by EVIDENCE STRENGTH, not by how interesting the finding is:
  "high"   — the pattern is unmistakable and quotable from BOTH articles
  "medium" — present but partial
  "low"    — suggestive only

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return ONLY valid JSON, no markdown fences. Include ALL SIX category keys.
Categories that do not apply need only {"applies": false}.

{
  "row_index": <int>,
  "categories": {
    "worthy_unworthy_victims": {
      "applies": true,
      "confidence": "high" | "medium" | "low",
      "finding": "<1-2 sentences, structural language only, no intent attribution>",
      "evidence_base": ["<verbatim quote from the base article>"],
      "evidence_candidate": ["<verbatim quote from the candidate article>"],
      "counterfactual_check": "<1 sentence: does this finding survive the swap test?>"
    },
    "agency_attribution":       {"applies": false},
    "presuppositions_doctrine": {"applies": false},
    "selective_criteria":       {"applies": false},
    "suppressed_alternative":   {"applies": false},
    "smoke_and_discrepancies":  {"applies": false}
  },
  "why_this_article": "<2-3 plain sentences written FOR THE READER: what does reading this article alongside the original let them see? Lead with the single strongest finding. No jargon, no category names, no intent language.>"
}
"""

CHOMSKY_PAIR_USER_TEMPLATE = """\
BASE ARTICLE — the article the reader is currently reading
─────────────────────────────────────────────
{base_text}

CANDIDATE ARTICLE
Outlet:         {cand_domain}
Source country: {cand_country}
Language:       {cand_language}
Title:          {cand_title}
─────────────────────────────────────────────
{cand_text}

─────────────────────────────────────────────
Possibly unreliable background on the candidate outlet's institutional position.
Use it only to inform your reasoning about structural position. Never assert it as
fact in any output field.
  Ownership:          {ownership_summary}
  State relationship: {state_relationship}
  Model's confidence: {confidence}
─────────────────────────────────────────────

Analyse this pair. The candidate's row_index is {row_index}.
"""


def chomsky_pair_analysis(base_text: str, candidate_row, outlet_context: dict,
                          client: OpenAI) -> dict:
    """
    One full-text pair analysis: base article <-> one candidate.
    Returns {row_index, categories, why_this_article}.
    """
    row_index = int(candidate_row.get("row_index", 0))

    user_prompt = CHOMSKY_PAIR_USER_TEMPLATE.format(
        base_text=base_text[:7000],
        cand_domain=str(candidate_row.get("domain", "unknown")),
        cand_country=str(candidate_row.get("sourcecountry", "unknown")),
        cand_language=str(candidate_row.get("language", "unknown")),
        cand_title=str(candidate_row.get("title", "")),
        cand_text=str(candidate_row.get("article_text", ""))[:7000],
        ownership_summary=outlet_context.get("ownership_summary", "unknown"),
        state_relationship=outlet_context.get("state_relationship", "unknown"),
        confidence=outlet_context.get("confidence", "low"),
        row_index=row_index,
    )

    raw = api_chat(
        client,
        system=CHOMSKY_PAIR_SYSTEM,
        user=user_prompt,
        max_tokens=3000,
        model=MODEL_FULL,
        response_format={"type": "json_object"},
    )

    try:
        data = json.loads(extract_json(raw))
    except json.JSONDecodeError as e:
        print(f"      [WARNING] Pair analysis returned unparseable JSON for row {row_index}: {e}")
        return {"row_index": row_index, "categories": _clean_categories({}),
                "why_this_article": ""}

    return {
        "row_index":        row_index,
        "categories":       _clean_categories(data.get("categories", {})),
        "why_this_article": str(data.get("why_this_article", "")).strip(),
    }


def _clean_categories(categories: dict) -> dict:
    """
    Normalises the LLM's category output and enforces the evidence rule in code:
    a category that applies but quotes nothing from either article is demoted to
    applies: false. The prompt states the rule; this makes it structural.
    """
    cleaned: dict[str, dict] = {}

    for name in CHOMSKY_CATEGORIES:
        cat = categories.get(name)
        if not isinstance(cat, dict) or not cat.get("applies"):
            cleaned[name] = {"applies": False}
            continue

        ev_base = [str(q).strip() for q in cat.get("evidence_base", []) if str(q).strip()]
        ev_cand = [str(q).strip() for q in cat.get("evidence_candidate", []) if str(q).strip()]

        if not ev_base and not ev_cand:
            cleaned[name] = {
                "applies":  False,
                "_demoted": "applies=true was returned with no verbatim evidence.",
            }
            continue

        confidence = str(cat.get("confidence", "low")).lower().strip()
        if confidence not in CONFIDENCE_WEIGHTS:
            confidence = "low"

        cleaned[name] = {
            "applies":              True,
            "confidence":           confidence,
            "finding":              str(cat.get("finding", "")).strip(),
            "evidence_base":        ev_base,
            "evidence_candidate":   ev_cand,
            "counterfactual_check": str(cat.get("counterfactual_check", "")).strip(),
        }

    return cleaned


# ─────────────────────────────────────────────
# STAGE 8 — SELECTION BY ILLUMINATION SCORE
# ─────────────────────────────────────────────
#
# The score is computed in Python, not by the LLM, so it is deterministic and
# debuggable: the same findings always produce the same ranking, and any ranking
# can be traced back to the categories that produced it.
# ─────────────────────────────────────────────

CONFIDENCE_WEIGHTS = {"high": 2.0, "medium": 1.0, "low": 0.25}

CATEGORY_WEIGHTS = {
    "worthy_unworthy_victims":  1.5,
    "suppressed_alternative":   1.5,
    "agency_attribution":       1.25,
    "presuppositions_doctrine": 1.0,
    "selective_criteria":       1.0,
    "smoke_and_discrepancies":  1.0,
}

# Plain-language lens names. The user never sees a raw category key.
CATEGORY_PLAIN_LABELS = {
    "worthy_unworthy_victims":  "different treatment of victims",
    "agency_attribution":       "who did it vs. what happened",
    "presuppositions_doctrine": "different assumptions",
    "selective_criteria":       "different standards applied",
    "suppressed_alternative":   "an account the original leaves out",
    "smoke_and_discrepancies":  "smoke / factual disagreement",
}


def score_illumination(categories: dict) -> tuple[float, list[dict]]:
    """
    Deterministic illumination score, plus a per-category breakdown for debugging.

    The 0.25 weight on low confidence is deliberate: stacking weak findings is nearly
    worthless, which reinforces the anti-over-finding guard at the scoring level rather
    than leaving it to the prompt alone.
    """
    breakdown: list[dict] = []
    total = 0.0

    for name, cat in categories.items():
        if not isinstance(cat, dict) or not cat.get("applies"):
            continue
        cat_w  = CATEGORY_WEIGHTS.get(name, 1.0)
        conf   = str(cat.get("confidence", "low")).lower()
        conf_w = CONFIDENCE_WEIGHTS.get(conf, CONFIDENCE_WEIGHTS["low"])
        points = conf_w * cat_w
        total += points
        breakdown.append({
            "category":    name,
            "confidence":  conf,
            "conf_weight": conf_w,
            "cat_weight":  cat_w,
            "points":      round(points, 3),
        })

    breakdown.sort(key=lambda b: b["points"], reverse=True)
    return round(total, 3), breakdown


def strongest_category(categories: dict) -> str:
    """The highest-weighted applying category, ties broken by confidence."""
    applying = [
        (name, cat) for name, cat in categories.items()
        if isinstance(cat, dict) and cat.get("applies")
    ]
    if not applying:
        return ""
    return max(
        applying,
        key=lambda kv: (
            CATEGORY_WEIGHTS.get(kv[0], 1.0),
            CONFIDENCE_WEIGHTS.get(str(kv[1].get("confidence", "low")).lower(), 0.25),
        ),
    )[0]


def select_by_illumination(candidates_df: pd.DataFrame, pair_analyses: list[dict],
                           event_country: str, max_count: int = MAX_DISPLAY) -> pd.DataFrame:
    """
    Ranks analysed pairs by their deterministic illumination score and takes the top
    max_count. Tiebreaker: a candidate whose sourcecountry matches the event country.

    candidates_df is the full-text DataFrame from Stage 6 (it carries `row_index`).
    """
    if candidates_df.empty or not pair_analyses:
        return pd.DataFrame()

    by_row = {int(row["row_index"]): row for _, row in candidates_df.iterrows()}
    event_ctry = normalize_country(event_country)

    ranked: list[dict] = []
    for pa in pair_analyses:
        idx = int(pa.get("row_index", -1))
        if idx not in by_row:
            continue
        row = by_row[idx]
        categories       = pa.get("categories", {})
        score, breakdown = score_illumination(categories)
        is_local = normalize_country(str(row.get("sourcecountry", ""))) == event_ctry
        ranked.append({
            "row_index":         idx,
            "row":               row,
            "illumination":      score,
            "breakdown":         breakdown,
            "categories":        categories,
            "why_this_article":  pa.get("why_this_article", ""),
            "is_local":          is_local,
        })

    if not ranked:
        return pd.DataFrame()

    ranked.sort(key=lambda r: (r["illumination"], 1 if r["is_local"] else 0), reverse=True)
    top = [r for r in ranked if r["illumination"] > 0][:max_count]

    # If nothing scored above zero, no pair produced an evidenced finding. Showing
    # the highest-ranked zero-score articles would be presenting an empty result as
    # a finding, so we surface nothing instead.
    if not top:
        return pd.DataFrame()

    out = pd.DataFrame([r["row"] for r in top]).reset_index(drop=True)
    out["illumination_score"] = [r["illumination"] for r in top]
    out["why_this_article"]   = [r["why_this_article"] for r in top]
    out["chomsky_findings"]   = [r["categories"] for r in top]
    out["strongest_category"] = [strongest_category(r["categories"]) for r in top]
    out["score_breakdown"]    = [r["breakdown"] for r in top]
    return out


# ─────────────────────────────────────────────
# STAGE 9 — SYNTHESIS
# ─────────────────────────────────────────────

SYNTHESIS_SYSTEM = """
You are writing a short synthesis for a reader who has just read one news article. You have
been given the findings from comparing that article against several others covering the same
event, analysed through Herman and Chomsky's propaganda model.

The model is STRUCTURAL, not conspiratorial. Coverage patterns follow from an outlet's
position, its audience, and its sourcing constraints — not from the intent of journalists.
Never write that an outlet "hid," "chose to suppress," or "deliberately" did anything, and
never call anything "propaganda by" anyone. Describe patterns as consequences of how the news
system is structured. No editorial directive is required for these patterns to appear.

Write "overall_synthesis": 3-4 sentences on what these articles collectively let the reader
see about how this event is covered. Be specific — name the outlets and name the patterns.
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

    # The note is a constant, not model output — it must never drift.
    return {"overall_synthesis": synthesis, "structural_note": STRUCTURAL_NOTE}


# ─────────────────────────────────────────────
# DISPLAY — USER-FACING AND DEV SECTIONS
# ─────────────────────────────────────────────
#
# Two audiences, two sections. The user-facing section carries no scores, no
# category names, and no outlet ownership context. The [DEV] section carries
# everything, including material that must never be shown to a user.
# ─────────────────────────────────────────────

def print_user_results(selected_df: pd.DataFrame, synthesis: dict) -> None:
    """Short, plain-language output. No scores, no category names, no jargon."""
    print(f"\n{'='*70}")
    print("  WHAT THESE ARTICLES TOGETHER LET YOU SEE")
    print(f"{'='*70}\n")

    overall = synthesis.get("overall_synthesis", "").strip()
    print(overall if overall else "(no synthesis available)")

    print(f"\n{synthesis.get('structural_note', STRUCTURAL_NOTE)}")

    if selected_df.empty:
        print("\nNo comparison articles surfaced for this story.")
        print(f"{'='*70}")
        return

    print(f"\n{'─'*70}")
    print("  ARTICLES")
    print(f"{'─'*70}")

    for i, (_, row) in enumerate(selected_df.iterrows(), start=1):
        lens = CATEGORY_PLAIN_LABELS.get(row.get("strongest_category", ""), "")
        print(f"\n  #{i}  {row.get('title', 'N/A')}")
        print(f"      {row.get('domain', 'N/A')} · {row.get('sourcecountry', 'N/A')}")
        if lens:
            print(f"      Lens: {lens}")
        print(f"      {row.get('why_this_article', '')}")
        print(f"      {row.get('url', '')}")

    print(f"\n{'='*70}")


def print_dev_results(fulltext_df: pd.DataFrame, pair_analyses: list[dict],
                      outlet_contexts: dict, selected_row_indices: set) -> None:
    """
    Verbose developer output for EVERY analysed pair, selected or not:
    full category table, evidence quotes, counterfactual checks, score breakdown,
    and the backend-only outlet context.
    """
    print(f"\n{'='*70}")
    print("  [DEV] FULL PAIR ANALYSIS — NOT USER-FACING")
    print(f"{'='*70}")

    if not pair_analyses:
        print("\n  [DEV] No pair analyses were produced.")
        return

    meta = {int(r["row_index"]): r for _, r in fulltext_df.iterrows()} if not fulltext_df.empty else {}

    for pa in sorted(pair_analyses, key=lambda p: p.get("row_index", 0)):
        idx        = int(pa.get("row_index", -1))
        row        = meta.get(idx, {})
        domain     = str(row.get("domain", "unknown"))
        categories = pa.get("categories", {})
        score, breakdown = score_illumination(categories)
        status     = "SELECTED" if idx in selected_row_indices else "not selected"

        print(f"\n{'─'*70}")
        print(f"  [DEV] row {idx} · {domain} · {row.get('sourcecountry', '?')} · {status}")
        print(f"        {str(row.get('title', ''))[:70]}")
        print(f"        illumination score: {score}")

        ctx = outlet_contexts.get(domain, {})
        print("\n        [BACKEND ONLY — never shown to users] outlet context:")
        print(f"          ownership          : {ctx.get('ownership_summary', 'unknown')}")
        print(f"          state relationship : {ctx.get('state_relationship', 'unknown')}")
        print(f"          model confidence   : {ctx.get('confidence', 'unknown')}")

        print("\n        score breakdown:")
        if breakdown:
            for b in breakdown:
                print(f"          {b['category']:<26} {b['confidence']:<7} "
                      f"{b['conf_weight']} × {b['cat_weight']} = {b['points']}")
            print(f"          {'TOTAL':<26} {' '*7} {' '*9} {score}")
        else:
            print("          (no categories applied — score 0)")

        print("\n        categories:")
        for name in CHOMSKY_CATEGORIES:
            cat = categories.get(name, {"applies": False})
            if not cat.get("applies"):
                demoted = cat.get("_demoted")
                suffix  = f"  [demoted: {demoted}]" if demoted else ""
                print(f"          {name:<26} applies: False{suffix}")
                continue
            print(f"          {name:<26} applies: True  ({cat.get('confidence')})")
            print(f"            finding    : {cat.get('finding', '')}")
            for q in cat.get("evidence_base", []):
                print(f"            base quote : \"{q}\"")
            for q in cat.get("evidence_candidate", []):
                print(f"            cand quote : \"{q}\"")
            print(f"            swap test  : {cat.get('counterfactual_check', '')}")

        print(f"\n        why_this_article: {pa.get('why_this_article', '')}")

    print(f"\n{'='*70}")


def dump_debug_run(payload: dict, dump_dir: str = DEBUG_DUMP_DIR) -> str:
    """
    Writes the whole run to debug_runs/<timestamp>.json so prompt iterations can be
    compared run over run. Returns the path written, or "" on failure.
    """
    try:
        os.makedirs(dump_dir, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path  = os.path.join(dump_dir, f"run_{stamp}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        return path
    except Exception as e:
        print(f"  [WARNING] Could not write debug dump: {e}")
        return ""


def _df_records(df: pd.DataFrame, drop: tuple[str, ...] = ()) -> list[dict]:
    """DataFrame -> JSON-serialisable records, optionally dropping heavy columns."""
    if df is None or df.empty:
        return []
    keep = [c for c in df.columns if c not in drop]
    return json.loads(df[keep].to_json(orient="records", default_handler=str))


# ─────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────

def run_clearframe_pipeline(
    source_url: str,
    api_key: str | None = None,
    max_gdelt_results: int = MAX_GDELT_RESULTS,
    max_candidates_rank: int = MAX_CANDIDATES_RANK,
    max_fulltext: int = MAX_FULLTEXT_CANDIDATES,
    top_n: int = MAX_DISPLAY
) -> dict:
    """
    Full ClearFrame pipeline, grounded in the Herman/Chomsky propaganda model.

    Provide a URL. The pipeline does the rest.

    Stages:
      1  trafilatura fetches the base article + publication date
      2  LLM builds a structured GDELT query plan
      3  GDELT returns candidate articles (+ regional fallback)
      4  LLM classifies the base article type
      5  Topical gate: binary same-event filter on title/metadata
      6  Full text fetched for up to max_fulltext gated candidates, local sources first
      7  Chomsky pair analysis: base <-> candidate, full text, per-category findings
      8  Selection: deterministic illumination score, top N
      9  Synthesis, display, and a timestamped debug dump

    Args:
        source_url          : URL of the article the user is reading
        api_key             : OpenAI API key (falls back to OPENAI_API_KEY env var)
        max_gdelt_results   : How many articles to pull from GDELT (default 50)
        max_candidates_rank : How many to pass to the topical gate (default 20)
        max_fulltext        : How many gated candidates to fetch full text for (default 10)
        top_n               : How many to show to the user (default 5)

    Returns:
        dict with all intermediate and final outputs for debugging
    """
    client = OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))

    def _early_exit(**extra) -> dict:
        base = {
            "source_url": source_url, "article_text": "", "plan": None, "query": None,
            "gdelt_df": pd.DataFrame(), "classification": None, "gate_results": [],
            "fulltext_df": pd.DataFrame(), "outlet_contexts": {}, "pair_analyses": [],
            "selected_df": pd.DataFrame(),
            "synthesis": {"overall_synthesis": "", "structural_note": STRUCTURAL_NOTE},
        }
        base.update(extra)
        return base

    # ── Stage 1: Fetch base article via trafilatura ───────────────────────
    print("\n[1/9] Fetching base article via trafilatura...")
    article_text, pub_date = get_article_text(source_url)
    if not article_text:
        raise ValueError(f"trafilatura could not extract text from: {source_url}")
    print(f"      Extracted {len(article_text)} characters.")
    print(f"      Preview: {article_text[:200]}...\n")

    # ── Stage 2: Build GDELT query plan ───────────────────────────────────
    print("[2/9] Building GDELT query plan...")
    plan               = make_query_plan(article_text, client)
    plan               = clean_plan(plan, max_terms=4)
    query, start_dt, end_dt = build_gdelt_query(
        plan["location"], plan["terms"], plan["source_country"],
        pub_date, plan["window_days_before"], plan["window_days_after"]
    )
    event_country = plan["source_country"]
    print(f"      Plan     : {plan}")
    print(f"      Query    : {query}")
    print(f"      Date range: {start_dt} → {end_dt}")
    print(f"      Event country (used to prefer local sources): {event_country}")

    # ── Stage 3: Search GDELT ─────────────────────────────────────────────
    print(f"\n[3/9] Searching GDELT ({start_dt[:8]} to {end_dt[:8]}, max={max_gdelt_results})...")
    gdelt_results = search_gdelt(query, startdatetime=start_dt, enddatetime=end_dt, maxrecords=max_gdelt_results)
    gdelt_df      = pd.DataFrame(gdelt_results.get("articles", []))
    print(f"      GDELT returned {len(gdelt_df)} articles.")

    # ── Stage 3b: Regional fallback if too few results ────────────────────
    if len(gdelt_df) < GDELT_FALLBACK_THRESHOLD:
        fallback_domain = get_fallback_domain(plan["source_country"])
        print(f"      Only {len(gdelt_df)} result(s) — below threshold ({GDELT_FALLBACK_THRESHOLD}). "
              f"Triggering regional fallback.")
        print(f"      Fallback domain: {fallback_domain} "
              f"(mapped from country: '{plan['source_country']}')")

        # Build the terms-only portion of the query (strip sourcecountry clause)
        loc         = quote_if_needed(plan["location"])
        tparts      = " OR ".join(quote_if_needed(t) for t in plan["terms"])
        terms_query = f"{loc} AND ({tparts})"

        fallback_results = search_gdelt_fallback(
            terms_query, fallback_domain, start_dt, end_dt, maxrecords=max_gdelt_results
        )
        fallback_df = pd.DataFrame(fallback_results.get("articles", []))

        if not fallback_df.empty:
            gdelt_df = (
                pd.concat([gdelt_df, fallback_df], ignore_index=True)
                .drop_duplicates(subset=["url"])
                .reset_index(drop=True)
            )
            print(f"      After fallback merge: {len(gdelt_df)} total article(s).")
        else:
            print(f"      [WARNING] Fallback search also returned 0 results. Continuing with what we have.")

    if gdelt_df.empty:
        print("      No results from GDELT. Exiting early.")
        return _early_exit(article_text=article_text, plan=plan, query=query)

    candidates_df = gdelt_df.head(max_candidates_rank).reset_index(drop=True)
    print(f"      Passing the first {len(candidates_df)} to the topical gate.")

    # ── Stage 4: Classify base article ───────────────────────────────────
    print("\n[4/9] Classifying base article type...")
    classification = classify_article(article_text, client)
    print(f"      Primary type : {classification.get('primary_type')}")
    print(f"      Secondary    : {classification.get('secondary_type')}")
    print(f"      Justification: {classification.get('justification')}")

    common = {"article_text": article_text, "plan": plan, "query": query,
              "gdelt_df": gdelt_df, "classification": classification}

    # ── Stage 5: Topical gate ────────────────────────────────────────────
    print(f"\n[5/9] Topical gate over {len(candidates_df)} candidates "
          f"(binary same-event filter — no scoring)...")
    gate_results = topical_gate(article_text, candidates_df, classification, client)

    n_pass = sum(1 for r in gate_results if r.get("topically_relevant"))
    for r in gate_results:
        verdict = "PASS" if r.get("topically_relevant") else "drop"
        domain  = str(candidates_df.iloc[r["row_index"]].get("domain", "?"))
        print(f"        [{verdict}] row {r['row_index']:<2} {domain:<28} {r.get('reason', '')}")
    print(f"      {n_pass}/{len(gate_results)} candidate(s) are about the same event.")

    if n_pass == 0:
        print("      Nothing passed the topical gate. Exiting early.")
        return _early_exit(**common, gate_results=gate_results)

    # ── Stage 6: Full-text fetch ─────────────────────────────────────────
    print(f"\n[6/9] Fetching full text (up to {max_fulltext}, local sources first)...")
    fulltext_df = fetch_candidate_texts(candidates_df, gate_results, event_country,
                                        max_candidates=max_fulltext)
    if fulltext_df.empty:
        print("      No candidate yielded usable full text. Exiting early.")
        return _early_exit(**common, gate_results=gate_results)

    # ── Stage 7: Chomsky pair analysis ───────────────────────────────────
    print(f"\n[7/9] Chomsky pair analysis over {len(fulltext_df)} full-text candidate(s)...")
    print(f"      Each pair is analysed against the base article across "
          f"{len(CHOMSKY_CATEGORIES)} categories.")
    print("      'applies: false' is expected — most pairs evidence only 1-3 categories.")

    outlet_contexts: dict[str, dict] = {}
    pair_analyses:   list[dict]      = []

    for n, (_, row) in enumerate(fulltext_df.iterrows(), start=1):
        domain = str(row.get("domain", "unknown"))
        print(f"\n      [{n}/{len(fulltext_df)}] {domain} (row {int(row['row_index'])})")

        ctx = get_outlet_context(domain, client)
        outlet_contexts[domain] = ctx
        print(f"           [BACKEND ONLY] outlet context — state relationship: "
              f"{ctx.get('state_relationship')} (confidence: {ctx.get('confidence')})")

        analysis = chomsky_pair_analysis(article_text, row, ctx, client)
        pair_analyses.append(analysis)

        applying = [n_ for n_, c in analysis.get("categories", {}).items() if c.get("applies")]
        score, _ = score_illumination(analysis.get("categories", {}))
        if applying:
            print(f"           Applies: {', '.join(applying)}")
        else:
            print("           Applies: none — no evidenced finding for this pair.")
        print(f"           Illumination score: {score}")

    # ── Stage 8: Selection by illumination score ─────────────────────────
    print(f"\n[8/9] Selecting top {top_n} by illumination score "
          f"(computed in Python, deterministic)...")
    selected_df = select_by_illumination(fulltext_df, pair_analyses, event_country,
                                         max_count=top_n)

    if selected_df.empty:
        print("      No pair produced an evidenced finding. Nothing to surface.")
        return _early_exit(**common, gate_results=gate_results,
                           fulltext_df=fulltext_df, outlet_contexts=outlet_contexts,
                           pair_analyses=pair_analyses)

    for i, (_, row) in enumerate(selected_df.iterrows(), start=1):
        print(f"        #{i}  {row['illumination_score']:<6} {row.get('domain', '?'):<28} "
              f"strongest: {row.get('strongest_category', '—')}")

    # ── Stage 9: Synthesis and display ───────────────────────────────────
    print(f"\n[9/9] Synthesising across the {len(selected_df)} selected pair(s)...")
    selected_rows      = set(int(r) for r in selected_df["row_index"])
    selected_for_synth = [
        {
            "outlet":           str(row.get("domain", "")),
            "source_country":   str(row.get("sourcecountry", "")),
            "title":            str(row.get("title", "")),
            "categories":       row.get("chomsky_findings", {}),
            "why_this_article": row.get("why_this_article", ""),
        }
        for _, row in selected_df.iterrows()
    ]
    synthesis = synthesize_brief(selected_for_synth, article_text, client)
    print("      Synthesis complete.")

    print_user_results(selected_df, synthesis)
    print_dev_results(fulltext_df, pair_analyses, outlet_contexts, selected_rows)

    dump_path = dump_debug_run({
        "timestamp":       datetime.now(timezone.utc).isoformat(),
        "source_url":      source_url,
        "plan":            plan,
        "query":           query,
        "classification":  classification,
        "gate_results":    gate_results,
        "fetched_text_metadata": [
            {"row_index": int(r["row_index"]), "domain": str(r.get("domain", "")),
             "url": str(r.get("url", "")), "sourcecountry": str(r.get("sourcecountry", "")),
             "is_local": bool(r.get("is_local", False)),
             "text_length": len(str(r.get("article_text", "")))}
            for _, r in fulltext_df.iterrows()
        ],
        "outlet_contexts": outlet_contexts,
        "pair_analyses":   pair_analyses,
        "scores": [
            {"row_index": int(pa["row_index"]),
             "illumination_score": score_illumination(pa.get("categories", {}))[0],
             "breakdown":          score_illumination(pa.get("categories", {}))[1]}
            for pa in pair_analyses
        ],
        "selected":  _df_records(selected_df, drop=("article_text",)),
        "synthesis": synthesis,
    })
    if dump_path:
        print(f"\n  [DEV] Full run dumped to: {dump_path}")

    return {
        "source_url":      source_url,
        "article_text":    article_text,
        "plan":            plan,
        "query":           query,
        "gdelt_df":        gdelt_df,
        "classification":  classification,
        "gate_results":    gate_results,
        "fulltext_df":     fulltext_df,
        "outlet_contexts": outlet_contexts,
        "pair_analyses":   pair_analyses,
        "selected_df":     selected_df,
        "synthesis":       synthesis,
    }


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":

    # Swap any of these in to test different article types
    # SOURCE_URL = "https://apnews.com/article/philippines-building-collapse-angeles-city-pampanga-clark-6a04bcd1f62ad8d625ab58a87512cd5c"
    # SOURCE_URL = "https://apnews.com/article/rwanda-genocide-suspect-kabuda-dies-hague-d9c0156deb1359429cb22ea8441974e9"
    # SOURCE_URL = "https://www.washingtonpost.com/world/2026/03/17/us-iran-israel-war-ali-larijani/"
    # SOURCE_URL = "https://www.aljazeera.com/news/2026/3/17/many-killed-wounded-after-blasts-hit-nigerias-maiduguri-witnesses-say"
    # SOURCE_URL = "https://www.who.int/news/item/09-01-2026-sudan-1000-days-of-war-deepen-the-world-s-worst-health-and-humanitarian-crisis"
    # SOURCE_URL = "https://www.nbcnews.com/world/north-korea/north-korea-fires-missiles-sea-show-force-seoul-rcna263450"
    # SOURCE_URL = "https://www.cbc.ca/news/world/venezuela-us-influence-trump-9.7122944"
    # SOURCE_URL = "https://www.nytimes.com/2026/03/14/business/media/washington-post-jeff-bezos-layoffs.html"
    # SOURCE_URL = "https://www.reuters.com/world/asia-pacific/hopes-dim-swift-end-iran-war-after-trump-speech-oil-prices-surge-anew-2026-04-02/"
    # SOURCE_URL = "https://apnews.com/article/iran-war-khamenei-politics-religion-society-a9e0405878db8266e1965d7c0b396243"
    SOURCE_URL = "https://apnews.com/article/ukraine-russia-war-kyiv-strikes-july-2026-83bcba8bb972ce248a805bc576a7322c"
    output = run_clearframe_pipeline(source_url=SOURCE_URL)
