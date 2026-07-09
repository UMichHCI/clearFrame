"""
ClearFrame Pipeline — v5
=========================
Architecture:
  Stage 1  — trafilatura fetches and extracts the base article text
  Stage 2  — LLM builds a structured GDELT query plan (location, country, terms, timespan)
  Stage 3  — GDELT DOC API returns up to 50 candidate articles matching the query
  Stage 4  — MediaRank backend source quality filter (top 30% cutoff, never shown to users)
  Stage 5  — Article classification: LLM classifies the base article type
             (breaking news / ongoing situation / economics-policy /
              historical-contextual / human-interest)
  Stage 6  — Relevance judgment: LLM decides relevance holistically using guiding questions
  Stage 7  — Select top 5 by confidence, local perspective preferred
  Stage 8  — trafilatura fetches full text of each selected article,
             then LLM runs a structured comparison against the base article
  Stage 9  — Display results

Install:
  pip install trafilatura openai pandas python-dotenv requests

.env:
  OPENAI_API_KEY=your-key

Sources:
  - ClearFrame paper (Ayyob et al., 2025)
  - trafilatura: https://trafilatura.readthedocs.io/
  - GDELT 2.0: https://blog.gdeltproject.org/gdelt-2-0-our-global-world-in-realtime/
  - MediaRank: Ye & Skiena, KDD 2019 (arxiv.org/abs/1903.07581)
  - Munson & Resnick, CHI 2010 (doi:10.1145/1753326.1753543)
"""

import json
import os
import csv
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


# Retained for potential future use — not currently called by the pipeline.
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

    for attempt in range(5):
        response = requests.get(GDELT_URL, params=params, timeout=30)
        print(f"  [DEBUG] GDELT HTTP status: {response.status_code} (attempt {attempt + 1})")
        if response.status_code != 429:
            break
        wait = 6 * (attempt + 1)
        print(f"  [DEBUG] Rate limited — waiting {wait}s before retry...")
        time.sleep(wait)

    try:
        return response.json()
    except Exception:
        print("[WARNING] GDELT did not return valid JSON:")
        print(response.text[:500])
        return {}


# ─────────────────────────────────────────────
# STAGE 4 — MEDIARANK SOURCE QUALITY FILTER
# ─────────────────────────────────────────────

# Retained for potential future use — not currently called by the pipeline.
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
# Design rationale — grounded in Entman (1993) and Boydstun et al. (2014)
# ────────────────────────────────────────────────────────────────────────
# Entman (1993) defines framing as selecting aspects of perceived reality and
# making them salient to promote problem definition, causal interpretation,
# moral evaluation, or treatment recommendation. Two articles about the same
# event can foreground entirely different aspects — one centering geopolitical
# stakes through a Security and defense frame, another centering affected families
# through a Quality of life or Morality frame. ClearFrame's goal is to surface
# that second article, not to find five articles that all confirm the first.
#
# Relevance is therefore not similarity — it is the degree to which a candidate
# article expands the set of salient aspects available to the reader. Scoring
# follows three independent dimensions: topical relevance as a gate, framing
# divergence as a ranking signal, and affected population salience as a ranking
# signal. The Boydstun et al. (2014) taxonomy of 15 framing dimensions
# (Card et al., ACL 2015) provides the controlled vocabulary for framing
# divergence and affected population salience.
# ─────────────────────────────────────────────

RELEVANCE_SYSTEM_TEMPLATE = """
You are scoring candidate news articles against a base article for the ClearFrame system.
The base article has been classified as: {primary_type}{secondary_note}.

ClearFrame's purpose is to show readers how the same story looks from different vantage
points. An article that says something DIFFERENT from the base article is more useful than
one that confirms it. Your job is not to find the most similar articles — it is to find
the ones that add the most to the reader's understanding by foregrounding aspects of the
story that the base article does not.

You will score each candidate on THREE independent dimensions. These are a framework for
structured judgment, not a checklist to fill out mechanically.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DIMENSION 1 — TOPICAL RELEVANCE (binary gate)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Is this candidate article about the same underlying event, situation, or subject as the
base article — interpreted appropriately for the article type?

This is a yes or no judgment, not a spectrum. If no, set all score fields to null and move
on. Do not score topically irrelevant articles on the other dimensions — they will be
excluded regardless of framing.

Output: topically_relevant: true or false.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DIMENSION 2 — FRAMING DIVERGENCE (1–5 ranking signal)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
First, identify the PRIMARY FRAMING DIMENSION of the base article — the single dimension
that most shapes what the base article treats as the central problem or focus. Record this
as base_primary_frame. This should be the same value across all candidates since it refers
to the same base article.

Then identify the PRIMARY FRAMING DIMENSION of the candidate article. Record this as
candidate_primary_frame.

Use the following 15 framing dimensions from Boydstun et al. (2014) and Card et al.
(ACL 2015) as your reference vocabulary. These are a thinking tool — use whichever ones
apply and ignore the rest:

  Economic | Capacity and resources | Morality | Fairness and equality |
  Legality and constitutionality | Policy prescription and evaluation |
  Crime and punishment | Security and defense | Health and safety |
  Quality of life | Cultural identity | Public opinion | Political |
  External regulation and reputation | Other

Score how much the difference between base_primary_frame and candidate_primary_frame
expands what is salient for the reader:

  5 — The candidate foregrounds a completely different framing dimension than the base
      article. A reader who only read the base article would encounter an aspect of the
      story they had no access to. Example: a base article with a Security and defense
      primary frame paired with a candidate whose primary frame is Quality of life,
      Morality, or Cultural identity.
  4 — The candidate foregrounds a meaningfully different dimension, or foregrounds the
      same dimension but from a clearly different institutional or geographic vantage
      point that shifts whose interests are centered.
  3 — The candidate partially overlaps in framing but introduces at least one secondary
      dimension not present in the base article.
  2 — The candidate uses mostly the same framing dimensions as the base article but with
      different facts or emphasis.
  1 — The candidate is essentially the same article in framing terms — same dimensions,
      same vantage point, same aspects made salient. Reading it adds nothing beyond
      confirming what the base article already said.

Output: framing_divergence_score: integer 1–5, or null if topically_relevant is false.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DIMENSION 3 — AFFECTED POPULATION SALIENCE (1–5 ranking signal)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
This captures the moral evaluation function of framing (Entman, 1993) — who is centered
as the primary victim, affected party, or moral subject of the story. It directly captures
whose experience is made visible.

  5 — The candidate centers a clearly DIFFERENT population as the primary affected group
      than the base article. Example: the base article centers government or institutional
      actors and the candidate centers civilians, families, or a specific community
      experiencing the event on the ground. Especially high-value when the candidate uses
      Morality, Quality of life, or Cultural identity framing to accomplish this.
  4 — The candidate shifts whose perspective or experience is foregrounded in a meaningful
      way, even if the affected group is broadly similar.
  3 — The candidate partially shifts perspective — some voices or communities appear that
      were absent in the base article, but the primary affected population is largely the same.
  2 — The candidate centers the same population with minor variation in whose quotes or
      experiences are included.
  1 — The candidate centers exactly the same actors and institutions as the base article.
      No new population is made visible.

Output: affected_population_score: integer 1–5, or null if topically_relevant is false.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RELATIONSHIP TO BASE (classification — NOT a quality judgment)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
This field describes what KIND of relationship the candidate has to the base article so the
reader understands what they gain from it. It is NOT a quality judgment and does NOT make an
article better or worse. Do not let a high or low framing/population score push you toward a
particular value here — they are independent. A corroborating article that confirms contested
facts across institutionally very different outlets is just as worth surfacing as a reframing
one; agreement between outlets with different pressures tells the reader the fact is not
contested or spun.

Pick the SINGLE best fit from exactly these three values:

  "corroborates" — reports substantially the same facts and confirms what the base article
      said. Its value is trust and certainty: when outlets with very different institutional
      pressures report the same casualty count or the same sequence of events, that agreement
      tells the reader the fact is solid.
  "extends" — adds new facts, populations, or context the base article lacked. Its value is
      completeness.
  "reframes" — reports largely the same facts but frames them differently or assigns the
      problem to different actors. Its value is perspective.

Output: relationship_to_base: one of "corroborates", "extends", or "reframes" (or null if
topically_relevant is false).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return ONLY a valid JSON array. No preamble, no markdown fences.

Each item must contain exactly these fields:
{{
  "row_index":                <integer matching the candidate's row_index>,
  "topically_relevant":       true | false,
  "base_primary_frame":       "<primary Boydstun dimension of the BASE article, or null if topically_relevant is false>",
  "candidate_primary_frame":  "<primary Boydstun dimension of THIS candidate, or null if topically_relevant is false>",
  "framing_divergence_score": <integer 1–5, or null if topically_relevant is false>,
  "affected_population_score":<integer 1–5, or null if topically_relevant is false>,
  "relationship_to_base":     "corroborates" | "extends" | "reframes" | null if topically_relevant is false,
  "reasoning":                "<2-3 sentences explaining what specific aspect this candidate makes salient that the base article does not, or why it is topically irrelevant>",
  "local_perspective":        true | false
}}
"""

def score_candidates(base_text: str, candidates_df: pd.DataFrame,
                     classification: dict, client: OpenAI) -> list[dict]:
    """
    Scores each candidate on three independent dimensions grounded in Entman (1993)
    and Boydstun et al. (2014):
      1. topically_relevant — binary gate (true/false)
      2. framing_divergence_score — 1–5, how much the candidate's primary frame
         differs from the base article's primary frame
      3. affected_population_score — 1–5, how much the candidate centers a
         different affected population than the base article

    Returns the raw JSON array from the LLM, with one dict per candidate.
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
    Selects up to max_count articles maximising framing diversity across the final set.

    Selection logic:
      1. Drop all candidates where topically_relevant is false.
      2. Compute combined = (framing_divergence_score * 0.6) + (affected_population_score * 0.4).
         The 0.6 weight reflects that expanding the framing is ClearFrame's primary goal;
         the 0.4 weight captures the moral evaluation dimension (Entman, 1993).
      3. Sort by combined descending; tiebreaker: prefer local_perspective = true.
      4. Relationship balancing: similarity is no longer a penalty. If more than one
         relationship_to_base type ("corroborates", "extends", "reframes") exists in the
         pool, guarantee at least one article of each present type — highest-scored of
         that type — before filling the remaining slots. This gives the reader all three
         KINDS of value (confirmation, completeness, perspective) when the pool allows it.
         If only one relationship type is present, fill purely by score / frame diversity.
      5. Frame diversity pass: fill remaining slots from the sorted list, skipping any
         candidate whose candidate_primary_frame has already been selected — unless no
         other candidates remain. This keeps the final set covering as many distinct
         Boydstun framing dimensions as possible.

    All scoring columns are attached to the output DataFrame for full transparency.
    """
    if not scored:
        return pd.DataFrame()

    # Step 1: drop topically irrelevant candidates
    topically_relevant = [
        r for r in scored if r.get("topically_relevant", False)
    ]
    if not topically_relevant:
        return pd.DataFrame()

    # Step 2: compute combined score
    for r in topically_relevant:
        fd = r.get("framing_divergence_score") or 0
        ap = r.get("affected_population_score") or 0
        r["combined"] = round((fd * 0.6) + (ap * 0.4), 2)

    # Step 3: sort by combined descending, local_perspective as tiebreaker
    sorted_candidates = sorted(
        topically_relevant,
        key=lambda r: (
            r["combined"],
            1 if r.get("local_perspective", False) else 0
        ),
        reverse=True
    )

    selected: list[dict] = []
    selected_ids: set = set()       # row_index of already-selected candidates
    seen_frames: set[str] = set()

    # Step 4: relationship balancing — surface all three KINDS of value when the
    # pool allows it. Corroboration and extension are no longer penalised; if more
    # than one relationship type is present, guarantee at least one article of each
    # present type (highest-scored of that type) before filling remaining slots by
    # score. If the pool contains only one relationship type, this is a no-op and we
    # just fall through to the frame-diversity / score fill below.
    RELATIONSHIP_TYPES = ["corroborates", "extends", "reframes"]
    present_types = {
        r.get("relationship_to_base")
        for r in sorted_candidates
        if r.get("relationship_to_base") in RELATIONSHIP_TYPES
    }
    if len(present_types) > 1:
        for rel in RELATIONSHIP_TYPES:
            if len(selected) >= max_count or rel not in present_types:
                continue
            for candidate in sorted_candidates:   # sorted by score desc
                if candidate["row_index"] in selected_ids:
                    continue
                if candidate.get("relationship_to_base") == rel:
                    selected.append(candidate)
                    selected_ids.add(candidate["row_index"])
                    frame = candidate.get("candidate_primary_frame", "") or ""
                    if frame:
                        seen_frames.add(frame)
                    break

    # Step 5: frame diversity pass — fill remaining slots, skipping any candidate
    # whose candidate_primary_frame is already represented (held back for backfill).
    deferred: list[dict] = []   # same-frame candidates held back for backfill

    for candidate in sorted_candidates:
        if len(selected) >= max_count:
            break
        if candidate["row_index"] in selected_ids:
            continue
        frame = candidate.get("candidate_primary_frame", "") or ""
        if frame and frame in seen_frames:
            deferred.append(candidate)
        else:
            selected.append(candidate)
            selected_ids.add(candidate["row_index"])
            if frame:
                seen_frames.add(frame)

    # Backfill with deferred (same-frame) candidates if slots remain
    for candidate in deferred:
        if len(selected) >= max_count:
            break
        if candidate["row_index"] in selected_ids:
            continue
        selected.append(candidate)
        selected_ids.add(candidate["row_index"])

    if not selected:
        return pd.DataFrame()

    selected_indices = [r["row_index"] for r in selected]
    selected_df      = candidates_df.iloc[selected_indices].copy().reset_index(drop=True)

    # Attach all scoring columns for full transparency
    meta_rows = []
    for r in selected:
        meta_rows.append({
            "row_index":                r["row_index"],
            "base_primary_frame":       r.get("base_primary_frame", ""),
            "candidate_primary_frame":  r.get("candidate_primary_frame", ""),
            "framing_divergence_score": r.get("framing_divergence_score"),
            "affected_population_score":r.get("affected_population_score"),
            "relationship_to_base":     r.get("relationship_to_base", ""),
            "combined":                 r["combined"],
            "reasoning":                r.get("reasoning", ""),
            "local_perspective":        r.get("local_perspective", False)
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
                    },
                    "framing_contrast":          {"type": "string"},
                    "comparative_note":          {"type": "string"},
                    "whose_story":               {"type": "string"}
                },
                "required": ["row_index", "summary", "similarities", "differences",
                             "source_country_perspective", "added_value", "overall_relatedness",
                             "framing_contrast", "comparative_note", "whose_story"],
                "additionalProperties": False
            }
        }
    },
    "required":             ["comparisons"],
    "additionalProperties": False
}

FULLTEXT_COMPARISON_SYSTEM = """
You are comparing full news articles against an original article.
Respond with a JSON object with a single key "comparisons" whose value is an array — one object per candidate.

For each candidate object include exactly these keys:
  "row_index"                — integer matching the candidate's row_index
  "summary"                  — 2-3 sentence summary of the candidate article
  "similarities"             — array of strings: ways it overlaps with the original
  "differences"              — array of strings: ways it diverges from the original
  "source_country_perspective" — string: what angle the source country adds (or "unclear")
  "added_value"              — string: what this article adds that the original lacks
  "overall_relatedness"      — one of: "very high", "high", "medium", "low"
  "framing_contrast"         — 1-2 sentences completing this structure: "Where the original article treats this as [X], this article treats it as [Y]." Name the specific framing shift. For example: "Where the original article treats this as a government security problem requiring military response, this article treats it as a community survival crisis experienced by families who have lost income and face daily displacement." If the framing is largely the same, say so plainly.
  "comparative_note"         — 1-2 sentences. When this article corroborates or largely REPEATS the original's facts, do NOT dismiss it. Hold the shared facts constant and describe what differs in PRESENTATION — emphasis, ordering, what is foregrounded versus buried, what surrounding context is added or omitted. When the underlying facts are identical across the two articles, the framing differences become the only variable, which makes the pair a controlled comparison the reader can learn from. For a corroborating/repeating article, complete this idea: "Both articles report [the shared fact], but where the original [does X with it], this article [does Y]." For a reframing or extending article, the note can instead briefly state what is genuinely new.
  "whose_story"              — 2 sentences: the first identifying whose experience this article centers as the primary human reality; the second identifying who is present in the original article but absent here, or absent in the original but present here. Be specific — name actual groups, not abstractions like "locals" or "communities."

Focus on: event overlap, geography, actors, timeline, framing, emphasis.
Infer perspective cautiously from article text, title, and metadata only.
"""

def compare_full_text(original_text: str, top_df: pd.DataFrame, client: OpenAI) -> pd.DataFrame:
    """
    For each selected article, trafilatura fetches the full text,
    then the LLM compares each article against the base article.
    """
    if top_df.empty:
        return pd.DataFrame()

    top_df = top_df.copy()

    # Fetch full text for each candidate using trafilatura
    article_texts = []
    for i, (_, row) in enumerate(top_df.iterrows()):
        url   = str(row.get("url", ""))
        title = str(row.get("title", ""))
        print(f"      [{i+1}/{len(top_df)}] Fetching: {title[:60]}...")
        text  = get_article_text(url)
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
# STAGE 9 — POPULATION ANALYSIS & COVERAGE MAP
# ─────────────────────────────────────────────
#
# Grounded in Entman's (1993) concept of moral evaluation in framing:
# every article implicitly assigns stakes and suffering to certain people
# over others, and that choice shapes what the reader understands as the
# problem and who it belongs to. This stage produces a cross-article
# synthesis — a coverage map — that tells the user whose perspective each
# outlet centers and what populations are missing from the original article.
# ─────────────────────────────────────────────

POPULATION_ANALYSIS_SYSTEM = """
You are analyzing a news article through the lens of Entman's (1993) framing theory,
specifically the moral evaluation component — who is implicitly assigned stakes, suffering,
or agency in this piece.

This is not about labeling ideology or bias. It is about identifying whose experience
the article treats as the central human reality of the story, and whose is absent or
reduced to statistics and background.

Return a JSON object with exactly these five keys:

  "primary_subject" — Who does this article center as the main affected party? Be specific —
    not "locals" but "fishing families in Sinaloa" or "U.S. border patrol agents." If the
    article centers an institution rather than people, name the institution and note that
    individuals are not centered.

  "secondary_subjects" — Who else appears in the article but only as context, statistics,
    or supporting detail? Return as an array of short descriptions.

  "absent_voices" — Based on the event being covered, who would logically have stakes here
    but does not appear or is only mentioned as an abstraction? This field is relational —
    reason about who the event affects in the real world and check whether those people are
    visible in this article. Be specific.

  "implicit_problem_definition" — In one sentence, what does this article implicitly define
    as the central problem? Whose definition of the problem does this serve?

  "outlet_context" — One sentence noting the outlet name, source country, and whether its
    geographic or institutional position might explain its centering choices. Keep this
    neutral and factual.

Return ONLY valid JSON. No preamble, no markdown fences.
"""

def analyze_article_populations(article_text: str, outlet_name: str,
                                 source_country: str, client: OpenAI,
                                 is_base_article: bool = False) -> dict:
    role_label  = "BASE ARTICLE (the article the user originally read)" if is_base_article else "COMPARISON ARTICLE"
    user_prompt = (
        f"Role: {role_label}\nOutlet: {outlet_name}\nSource country: {source_country}\n\n"
        f"Article text:\n{article_text[:6000]}"
    )
    raw = api_chat(
        client,
        system=POPULATION_ANALYSIS_SYSTEM,
        user=user_prompt,
        max_tokens=800,
        model=MODEL_FULL,
        response_format={"type": "json_object"}
    )
    return json.loads(extract_json(raw))


COVERAGE_MAP_SYSTEM = """
You have analyzed multiple articles covering the same news event from different outlets.
Your task is to synthesize what a reader learns by seeing them together versus only reading
the original article — and to reason explicitly about why that difference matters.

Before producing your output, work through the following four reasoning steps. Store your
full reasoning in the llm_reasoning field so it can be read and evaluated during development.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REASONING CHAIN (stored in llm_reasoning)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Step 1 — What understanding does the base article produce?
If a reader only read the base article, what would they conclude? Who would they think the
event happened to? What would they think the central problem is? What solution would feel
natural given that framing? Be specific — name the actual groups and problem definitions
the base article produces. (3–5 sentences)

Step 2 — What does each additional article add or contest?
For each local article, answer: does this article confirm the base article's understanding,
extend it with new facts, or reframe it by centering different people or defining a different
problem? If it reframes, what specifically changes about the reader's understanding? Name
the concrete difference. (3–5 sentences total across all articles)

Step 3 — What would the reader have gotten wrong or missed entirely?
If they only read the base article, what specific misconception or gap would they carry?
Is there a population they would not know was affected? A factual claim they would treat as
settled that is actually contested? A solution that would seem obvious that the local framing
shows is inadequate or harmful? (3–5 sentences)

Step 4 — Why does this matter beyond "getting a different perspective"?
Push past the generic. Reason about what practical or epistemic difference the additional
framing makes. Does it change who the reader might hold responsible? Does it reveal that
the event is still ongoing when the base article implied closure? Does it show that a policy
the base article treats as a solution is experienced as a harm by affected communities?
(3–5 sentences)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Return a single JSON object with exactly these six keys:

"llm_reasoning" — A JSON object with exactly four keys:
  "step1_base_understanding"   : your Step 1 reasoning (3–5 sentences)
  "step2_article_contributions": your Step 2 reasoning (3–5 sentences)
  "step3_reader_gaps"          : your Step 3 reasoning (3–5 sentences)
  "step4_why_it_matters"       : your Step 4 reasoning (3–5 sentences)

"population_landscape" — A list of all distinct affected groups that appear across all
  articles combined. For each group, note which outlets center them, which mention them
  peripherally, and which ignore them entirely. Be specific — name actual groups, not
  abstractions.

"blind_spots" — Which affected populations appear in only one or two of the local articles
  but not in the base article? What does a reader who only read the base article not know
  exists? This is the most important field — be specific and name the outlets that reveal
  each blind spot.

"narrative_tension" — Where do the articles most sharply disagree, not in facts but in who
  the problem belongs to? Which outlets frame this as a government problem, a security
  problem, a community survival problem, and so on?

"theory_of_change_explanation" — A plain-language explanation written for the user, 3–4
  sentences, answering: why should you care that these articles frame the story differently?
  Do not say "to get a different perspective." Instead name the specific gap that ClearFrame
  is filling for this particular story. Use your Step 4 reasoning to ground this. This is
  displayed to the user above the summary.

"user_summary" — 2–3 sentences written for a non-expert reader. Frame it as: these articles
  tell different stories about who this event affects. Be specific — name actual groups and
  outlets.

Return ONLY valid JSON. No preamble, no markdown fences.
"""

def synthesize_coverage_map(population_analyses: list[dict],
                             base_article_text: str, client: OpenAI) -> dict:
    analyses_text = json.dumps(population_analyses, ensure_ascii=False, indent=2)
    user_prompt = (
        f"Base article text (first 3000 characters):\n{base_article_text[:3000]}\n\n"
        f"Per-article population analyses:\n{analyses_text}"
    )
    raw = api_chat(
        client,
        system=COVERAGE_MAP_SYSTEM,
        user=user_prompt,
        max_tokens=3000,
        model=MODEL_FULL,
        response_format={"type": "json_object"}
    )
    data = json.loads(extract_json(raw))

    # Print reasoning chain for development inspection
    reasoning = data.get("llm_reasoning", {})
    print(f"\n{'─'*70}")
    print("  [DEV] LLM REASONING CHAIN")
    print("  " + "=" * 26)
    for step_key, label in [
        ("step1_base_understanding",    "Step 1 — Base article understanding"),
        ("step2_article_contributions", "Step 2 — Article contributions"),
        ("step3_reader_gaps",           "Step 3 — Reader gaps"),
        ("step4_why_it_matters",        "Step 4 — Why it matters"),
    ]:
        print(f"\n  {label}:\n  {reasoning.get(step_key, '(missing)')}")
    print(f"\n{'─'*70}\n")

    return data


# ─────────────────────────────────────────────
# DISPLAY HELPERS
# ─────────────────────────────────────────────

def print_results(comparison_df: pd.DataFrame, coverage_map: dict | None = None,
                  n: int = MAX_DISPLAY):
    if comparison_df.empty:
        print("No results to display.")
        return

    if coverage_map:
        print(f"\n{'='*70}")
        print("  COVERAGE MAP — WHO THIS STORY IS ABOUT ACROSS OUTLETS")
        print(f"{'='*70}")
        print(f"\nWHY THIS MATTERS:")
        print(coverage_map.get("theory_of_change_explanation", "(missing)"))
        print(f"\nIN SHORT:")
        print(coverage_map.get("user_summary", "(missing)"))
        print(f"\nWHO APPEARS WHERE:")
        print(coverage_map.get("population_landscape", "(missing)"))
        print(f"\nWHAT THE ORIGINAL ARTICLE LEFT OUT:")
        print(coverage_map.get("blind_spots", "(missing)"))
        print(f"\nWHERE THE ARTICLES DISAGREE ON WHO OWNS THIS PROBLEM:")
        print(coverage_map.get("narrative_tension", "(missing)"))
        print(f"\n{'─'*54}")
        print("  ARTICLES")

    for i, (_, row) in enumerate(comparison_df.head(n).iterrows(), start=1):
        title             = row.get("title", "N/A")
        url               = row.get("url", "")
        source            = row.get("sourcecountry", "N/A")
        domain            = row.get("domain", "N/A")
        language          = row.get("language", "N/A")
        relatedness       = row.get("overall_relatedness", "N/A")
        reasoning         = row.get("reasoning", "")
        summary           = row.get("summary", "")
        similarities      = row.get("similarities", [])
        differences       = row.get("differences", [])
        perspective       = row.get("source_country_perspective", "")
        added_value       = row.get("added_value", "")
        framing_contrast  = row.get("framing_contrast", "")
        comparative_note  = row.get("comparative_note", "")
        whose_story       = row.get("whose_story", "")

        base_frame     = row.get("base_primary_frame", "N/A")
        cand_frame     = row.get("candidate_primary_frame", "N/A")
        fd_score       = row.get("framing_divergence_score", "N/A")
        ap_score       = row.get("affected_population_score", "N/A")
        relationship   = row.get("relationship_to_base", "N/A")
        combined       = row.get("combined", "N/A")

        relationship_value = {
            "corroborates": "confirms the facts",
            "extends":      "adds new context",
            "reframes":     "frames it differently",
        }.get(relationship, "")

        print(f"\n{'='*70}")
        print(f"  #{i}  {title}")
        print(f"  URL                 : {url}")
        print(f"  Source              : {source} | Domain: {domain} | Language: {language}")
        print(f"  Base article frame  : {base_frame}")
        print(f"  This article frame  : {cand_frame}")
        print(f"  Framing divergence  : {fd_score}/5")
        print(f"  Affected population : {ap_score}/5")
        rel_suffix = f"  ({relationship_value})" if relationship_value else ""
        print(f"  Relationship to original : {relationship}{rel_suffix}")
        print(f"  Combined            : {combined}")
        print(f"  Overall related     : {relatedness}")
        print(f"\n  RELEVANCE REASONING:\n  {reasoning}")
        if framing_contrast:
            print(f"\n  FRAMING CONTRAST:\n  {framing_contrast}")
        if comparative_note:
            print(f"\n  COMPARATIVE NOTE:\n  {comparative_note}")
        print(f"\n  SUMMARY:\n  {summary}")
        print(f"\n  SIMILARITIES:")
        for s in similarities:
            print(f"    • {s}")
        print(f"\n  DIFFERENCES:")
        for d in differences:
            print(f"    • {d}")
        print(f"\n  SOURCE-COUNTRY PERSPECTIVE:\n  {perspective}")
        if whose_story:
            print(f"\n  WHOSE STORY:\n  {whose_story}")
        print(f"\n  ADDED VALUE:\n  {added_value}")

    print(f"\n{'='*70}")


# ─────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────

def run_clearframe_pipeline(
    source_url: str,
    mediarank_filepath: str = "data/mediarank_rankings.csv",
    api_key: str | None = None,
    max_gdelt_results: int = MAX_GDELT_RESULTS,
    max_candidates_rank: int = MAX_CANDIDATES_RANK,
    top_n: int = MAX_DISPLAY
) -> dict:
    """
    Full ClearFrame pipeline (v5 — trafilatura edition).

    Provide a URL. The pipeline does the rest.

    Stages:
      1  trafilatura fetches the base article
      2  LLM builds a structured GDELT query plan
      3  GDELT returns candidate articles
      4  LLM classifies the base article type
      5  LLM makes a holistic relevance judgment for each candidate
      6  Select top 5 by confidence, local perspective preferred
      7  trafilatura fetches full text of each selected article, LLM compares
         + population analysis and coverage map synthesis (Entman 1993)
         + print and return results

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

    # ── Stage 1: Fetch base article via trafilatura ───────────────────────
    print("\n[1/7] Fetching base article via trafilatura...")
    article_text, pub_date = get_article_text(source_url)
    if not article_text:
        raise ValueError(f"trafilatura could not extract text from: {source_url}")
    print(f"      Extracted {len(article_text)} characters.")
    print(f"      Preview: {article_text[:200]}...\n")

    # ── Stage 2: Build GDELT query plan ───────────────────────────────────
    print("[2/7] Building GDELT query plan...")
    plan               = make_query_plan(article_text, client)
    plan               = clean_plan(plan, max_terms=4)
    query, start_dt, end_dt = build_gdelt_query(
        plan["location"], plan["terms"], plan["source_country"],
        pub_date, plan["window_days_before"], plan["window_days_after"]
    )
    print(f"      Plan     : {plan}")
    print(f"      Query    : {query}")
    print(f"      Date range: {start_dt} → {end_dt}")

    # ── Stage 3: Search GDELT ─────────────────────────────────────────────
    print(f"\n[3/7] Searching GDELT ({start_dt[:8]} to {end_dt[:8]}, max={max_gdelt_results})...")
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
        return {"source_url": source_url, "article_text": article_text,
                "plan": plan, "query": query, "gdelt_df": gdelt_df,
                "selected_df": pd.DataFrame(), "comparison_df": pd.DataFrame()}

    candidates_df = gdelt_df.head(max_candidates_rank).reset_index(drop=True)

    # ── Stage 4: Classify base article ───────────────────────────────────
    print(f"\n[4/7] Classifying base article type...")
    classification = classify_article(article_text, client)
    print(f"      Primary type : {classification.get('primary_type')}")
    print(f"      Secondary    : {classification.get('secondary_type')}")
    print(f"      Justification: {classification.get('justification')}")

    # ── Stage 5: Relevance scoring ────────────────────────────────────────
    print(f"\n[5/7] Judging relevance of {len(candidates_df)} candidates...")
    scored = score_candidates(article_text, candidates_df, classification, client)

    print(f"      Scored {len(scored)} candidates")

    for r in sorted(scored, key=lambda x: x.get("framing_divergence_score") or 0, reverse=True):
        relevant   = r.get("topically_relevant", False)
        fd         = r.get("framing_divergence_score", "n/a") if relevant else "—"
        ap         = r.get("affected_population_score", "n/a") if relevant else "—"
        frame      = r.get("candidate_primary_frame", "?") if relevant else "excluded"
        combined   = round((r.get("framing_divergence_score") or 0) * 0.6 +
                           (r.get("affected_population_score") or 0) * 0.4, 2) if relevant else "—"
        print(f"        relevant: {str(relevant):<5}  fd: {fd}/5  ap: {ap}/5  combined: {combined}  frame: {frame}  row {r['row_index']}")

    # ── Stage 6: Select top articles ─────────────────────────────────────
    print(f"\n[6/7] Selecting top {top_n} articles...")
    selected_df = select_top_articles(candidates_df, scored, max_count=top_n)
    print(f"      {len(selected_df)} article(s) selected.")

    if selected_df.empty:
        print("      No articles passed selection criteria.")
        return {"source_url": source_url, "article_text": article_text,
                "plan": plan, "query": query, "gdelt_df": gdelt_df,
                "classification": classification, "scored": scored,
                "selected_df": pd.DataFrame(), "comparison_df": pd.DataFrame()}

    # ── Stage 7: Full-text comparison via trafilatura ────────────────────
    print(f"\n[7/7] Fetching full text via trafilatura and comparing top {len(selected_df)} articles...")
    comparison_df = compare_full_text(article_text, selected_df, client)
    print(f"      Comparison complete for {len(comparison_df)} article(s).")

    # ── Stage 9: Population analysis and coverage map ────────────────────
    coverage_map      = None
    population_analyses: list[dict] = []

    if comparison_df.empty:
        print("\n[coverage map] Skipping coverage map — no comparison articles available.")
    else:
        def _extract_text(val) -> str:
            """Safely extract plain text from article_text column (may be tuple or str)."""
            if isinstance(val, tuple):
                return val[0] if val else ""
            return str(val) if val else ""

        articles_with_text = [
            row for _, row in comparison_df.iterrows()
            if _extract_text(row.get("article_text", "")).strip()
        ]

        if len(articles_with_text) < 2:
            print("\n[coverage map] Skipping coverage map — fewer than 2 articles with retrievable full text.")
        else:
            print(f"\n[coverage map] Running population analysis across {len(articles_with_text) + 1} articles "
                  f"(base + {len(articles_with_text)} local)...")

            # Analyze base article
            base_analysis = analyze_article_populations(
                article_text, "base article", "base", client, is_base_article=True
            )
            base_analysis["_label"] = "BASE ARTICLE"
            base_analysis["is_base"] = True
            population_analyses.append(base_analysis)
            print(f"      [base article] → primary subject: {base_analysis.get('primary_subject', '?')}")

            # Analyze each selected article
            for _, row in comparison_df.iterrows():
                text_val     = _extract_text(row.get("article_text", ""))
                outlet_name  = str(row.get("domain", "unknown"))
                source_ctry  = str(row.get("sourcecountry", "unknown"))
                if not text_val.strip():
                    continue
                analysis = analyze_article_populations(text_val, outlet_name, source_ctry, client)
                analysis["_label"] = outlet_name
                population_analyses.append(analysis)
                print(f"      [{outlet_name}] → primary subject: {analysis.get('primary_subject', '?')}")

            # Synthesize coverage map
            print(f"      Synthesizing coverage map...")
            coverage_map = synthesize_coverage_map(population_analyses, article_text, client)

    # ── Stage 10: Display ────────────────────────────────────────────────
    print_results(comparison_df, coverage_map=coverage_map, n=top_n)

    return {
        "source_url":          source_url,
        "article_text":        article_text,
        "plan":                plan,
        "query":               query,
        "gdelt_df":            gdelt_df,
        "classification":      classification,
        "scored":              scored,
        "selected_df":         selected_df,
        "comparison_df":       comparison_df,
        "population_analyses": population_analyses,
        "coverage_map":        coverage_map,
    }


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":

    # Swap any of these in to test different article types
    SOURCE_URL = "https://apnews.com/article/philippines-building-collapse-angeles-city-pampanga-clark-6a04bcd1f62ad8d625ab58a87512cd5c"
    # SOURCE_URL = "https://apnews.com/article/rwanda-genocide-suspect-kabuda-dies-hague-d9c0156deb1359429cb22ea8441974e9"
    # SOURCE_URL = "https://www.washingtonpost.com/world/2026/03/17/us-iran-israel-war-ali-larijani/"
    # SOURCE_URL = "https://www.aljazeera.com/news/2026/3/17/many-killed-wounded-after-blasts-hit-nigerias-maiduguri-witnesses-say"
    # SOURCE_URL = "https://www.who.int/news/item/09-01-2026-sudan-1000-days-of-war-deepen-the-world-s-worst-health-and-humanitarian-crisis"
    # SOURCE_URL = "https://www.nbcnews.com/world/north-korea/north-korea-fires-missiles-sea-show-force-seoul-rcna263450"
    # SOURCE_URL = "https://www.cbc.ca/news/world/venezuela-us-influence-trump-9.7122944"
    # SOURCE_URL = "https://www.nytimes.com/2026/03/14/business/media/washington-post-jeff-bezos-layoffs.html"
    # SOURCE_URL = "https://www.reuters.com/world/asia-pacific/hopes-dim-swift-end-iran-war-after-trump-speech-oil-prices-surge-anew-2026-04-02/"


    output = run_clearframe_pipeline(
        source_url=SOURCE_URL,
        mediarank_filepath="data/mediarank_rankings.csv"  # optional — skipped if not present
    )