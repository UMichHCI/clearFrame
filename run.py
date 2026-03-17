"""
ClearFrame Article Relevance Pipeline — v3
============================================
New in this version:
  - Stage 0: The LLM uses the built-in web_search tool to autonomously find
    candidate articles based on the base article's extracted event metadata.
    No manual candidate list is required. The pipeline is now fully self-contained:
    you provide a base article, it finds and ranks everything else.

Unchanged from v2:
  - Stage 1: Metadata extraction from the base article.
  - Stage 2: MediaRank backend source quality filter (top 30% cutoff).
             NewsGuard will be added here once the academic license is obtained.
  - Stage 3: Explicit 9-question relevance checklist scored by the LLM.
  - Stage 4: Select up to 5 articles, ranked by relevance score.
  - No factual delta extraction yet (deferred to a future sprint).

How Stage 0 works:
  The LLM is given the extracted event metadata and a set of search query templates.
  It issues multiple targeted searches using the Anthropic web_search tool, then
  parses the results to build a pool of CandidateArticle objects. This approach
  is grounded in ClearFrame's design goal of surfacing geographically proximate,
  event-aligned coverage (ClearFrame paper, Ayyob et al., 2025).

Sources:
  - ClearFrame paper (Ayyob et al., 2025)
  - MediaRank: Ye & Skiena, KDD 2019 (arxiv.org/abs/1903.07581)
  - Munson & Resnick, CHI 2010 (doi:10.1145/1753326.1753543)
"""

import json
import os
import csv
import re
import time
from urllib.parse import urlparse
from dotenv import load_dotenv
from openai import OpenAI, RateLimitError

load_dotenv()


def extract_json(text: str) -> str:
    """Strip markdown code fences if present, returning raw JSON text."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def api_chat(client: OpenAI, system: str, user: str, max_tokens: int = 2000,
             model: str | None = None) -> str:
    """Chat completion with exponential backoff on rate limits. Returns response text."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    chosen_model = model or OPENAI_MINI_MODEL
    for attempt in range(6):
        try:
            resp = client.chat.completions.create(
                model=chosen_model,
                messages=messages,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content.strip()
        except RateLimitError:
            wait = 2 ** attempt
            print(f"      [Rate limit] Waiting {wait}s before retry (attempt {attempt + 1}/6)...")
            time.sleep(wait)
    raise RuntimeError("Exceeded max retries due to rate limiting.")


def api_search(client: OpenAI, instruction: str) -> str:
    """Runs a web search via the OpenAI Responses API. Returns the response text."""
    for attempt in range(6):
        try:
            resp = client.responses.create(
                model=OPENAI_SEARCH_MODEL,
                tools=[{"type": "web_search"}],
                input=instruction,
            )
            return resp.output_text.strip()
        except RateLimitError:
            wait = 2 ** attempt
            print(f"      [Rate limit] Waiting {wait}s before retry (attempt {attempt + 1}/6)...")
            time.sleep(wait)
    raise RuntimeError("Exceeded max retries due to rate limiting.")

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

OPENAI_MODEL        = "gpt-4o"        # used for complex reasoning (relevance scoring)
OPENAI_MINI_MODEL   = "gpt-4o-mini"  # used for lighter tasks (extraction, parsing, query gen)
OPENAI_SEARCH_MODEL = "gpt-5"        # used for web search via Responses API

# MediaRank: rank out of 50,695 total sources (Ye & Skiena, KDD 2019).
# Top 30% cutoff = rank ≤ 15,208. Backend filter only — never displayed to users.
MEDIARANK_TOTAL_SOURCES = 50_695
MEDIARANK_CUTOFF_PERCENTILE = 0.30
MEDIARANK_CUTOFF_RANK = int(MEDIARANK_TOTAL_SOURCES * MEDIARANK_CUTOFF_PERCENTILE)

# How many search queries to issue when finding candidates (Stage 0).
# More queries = broader candidate pool, but more API calls.
MAX_SEARCH_QUERIES = 5

# Maximum candidates to carry forward into relevance scoring.
MAX_CANDIDATE_POOL = 20

# Maximum articles to show to the user.
MAX_DISPLAY_ARTICLES = 5

# Minimum relevance score to pass (out of 100).
RELEVANCE_SCORE_THRESHOLD = 60


# ─────────────────────────────────────────────
# MEDIARANK LOADER
# ─────────────────────────────────────────────

def load_mediarank_data(filepath: str) -> dict[str, int]:
    """
    Loads MediaRank data into a domain → rank lookup dict.
    Export from: https://www.media-rank.com/filter#

    Expected CSV columns: domain, rank, ...
    Returns dict mapping domain → global rank (lower = better quality).
    If the file is not found, returns an empty dict and logs a warning.
    """
    ranks: dict[str, int] = {}

    if not os.path.exists(filepath):
        print(f"[WARNING] MediaRank file not found at '{filepath}'. "
              f"MediaRank filter will be skipped until the file is added.")
        return ranks

    with open(filepath, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            domain = row.get("domain", "").lower().strip()
            rank = row.get("rank")
            if domain and rank:
                try:
                    ranks[domain] = int(rank)
                except ValueError:
                    pass

    print(f"[INFO] Loaded {len(ranks)} MediaRank domain ranks from '{filepath}'.")
    return ranks


# ─────────────────────────────────────────────
# DATA MODELS
# ─────────────────────────────────────────────

class ArticleMetadata:
    """Structured event metadata extracted from the base article."""
    def __init__(self, summary: str, city: str, region: str, country: str,
                 event_date_range: str, entity_list: list[str]):
        self.summary = summary
        self.city = city
        self.region = region
        self.country = country
        self.event_date_range = event_date_range
        self.entity_list = entity_list


class CandidateArticle:
    """A candidate article discovered via web search or provided manually."""
    def __init__(self, article_id: str, title: str, url: str,
                 source_name: str, domain: str,
                 mediarank_rank: int | None = None,
                 snippet: str = ""):
        self.article_id = article_id
        self.title = title
        self.url = url
        self.source_name = source_name
        self.domain = domain.lower().strip()
        self.mediarank_rank = mediarank_rank
        self.snippet = snippet  # search result excerpt, used in relevance scoring

    def passes_source_filter(self) -> tuple[bool, str]:
        """
        Hard source quality gate — backend only, never shown to users.
        MediaRank rank must be within top 30% globally (≤ 15,208 / 50,695).
        Sources with no rank data are allowed through.
        NOTE: NewsGuard check added here once academic license is obtained.
        """
        if self.mediarank_rank is not None:
            if self.mediarank_rank > MEDIARANK_CUTOFF_RANK:
                return False, (
                    f"MediaRank rank {self.mediarank_rank} is outside the top 30% "
                    f"(cutoff: rank ≤ {MEDIARANK_CUTOFF_RANK} / {MEDIARANK_TOTAL_SOURCES})."
                )
        return True, "passes"


class RelevanceResult:
    """Output of the LLM relevance scoring stage for one candidate."""
    def __init__(self, article_id: str, score: int, label: str,
                 hard_fail: bool, checklist_answers: dict[str, str],
                 need_full_text: bool):
        self.article_id = article_id
        self.score = score
        self.label = label
        self.hard_fail = hard_fail
        self.checklist_answers = checklist_answers
        self.need_full_text = need_full_text


# ─────────────────────────────────────────────
# STAGE 0: WEB SEARCH — FIND CANDIDATE ARTICLES
# ─────────────────────────────────────────────
#
# The LLM is given the extracted event metadata and a set of explicit search
# query templates. It issues multiple web searches and parses the results into
# a structured list of CandidateArticle objects.
#
# Query strategy (grounded in ClearFrame paper Section 3.3):
#   The pipeline looks for articles that are:
#     (1) Geographically proximate to the event location
#     (2) About the same specific event (not just the same topic)
#     (3) From outlets in the event's country or region
#     (4) Published within the event's timeframe
#
# We issue multiple queries to maximize coverage across:
#   - English-language international sources covering the event
#   - Local-language sources in the event country
#   - Specific named entities / actors involved
# ─────────────────────────────────────────────

SEARCH_QUERY_SYSTEM_PROMPT = """You are a research assistant helping find LOCAL news coverage of a specific event.

Your goal is to find how news outlets IN THE EVENT'S COUNTRY reported on this event — NOT coverage from
American or Western international media (CNN, BBC, Reuters, NYT, etc. are already known).

Given event metadata, generate {max_queries} targeted web search queries following these rules:

  MANDATORY:
  - At least 3 of the {max_queries} queries MUST be written in the local/official language(s) of the event country.
    (e.g. Arabic for Iraq, Spanish for Mexico/Cuba, French for France, etc.)
  - At least 1 query should use a country-specific domain hint (e.g. site:.iq, site:.mx, site:.fr).
    EXCEPTION: Do NOT use site:.cu — Cuba's internet is government-controlled and not publicly indexed.
    For Cuba, instead target known diaspora outlets: site:14ymedio.com OR site:cibercuba.com OR site:radiomartí.com
  - Every query must target the SPECIFIC incident, not the general topic.

  AVOID:
  - Generic English queries that will return CNN/BBC/Reuters/NYT results.
  - Broad topic queries (e.g. "US military Iraq" — too vague).
  - site:.cu (Cuba only — those domains are not publicly accessible).

  FORMAT:
  - Keep queries short (4–8 words), factual, no opinion words.
  - Vary the queries — do not rephrase the same query.

Return ONLY a valid JSON array of query strings. No preamble, no markdown fences.
Example for an event in Iraq: ["تحطم طائرة KC-135 العراق 2026", "site:.iq طائرة عسكرية أمريكية", "KC-135 crash Irak mars 2026"]
Example for Cuba: ["Trump tomar Cuba 2026", "site:14ymedio.com apagón Cuba", "Díaz-Canel inversión extranjera marzo 2026"]
"""

SEARCH_RESULT_PARSE_SYSTEM_PROMPT = """You are parsing web search results to extract news article metadata.

Given raw search results, extract each distinct news article found and return structured data.
Only include items that are clearly news articles (not homepages, wikis, social media, or forums).

Return ONLY a valid JSON array. No preamble, no markdown fences.

Each item:
{
  "title": "<article headline>",
  "url": "<full URL>",
  "source_name": "<outlet name, e.g. Reuters, Vanguardia>",
  "domain": "<domain only, e.g. reuters.com>",
  "snippet": "<1-2 sentence excerpt from the search result, or empty string if none>"
}

If a URL appears in multiple search results, only include it once (deduplicate by URL).
If fewer than 3 clear articles are found, return whatever is available."""


def generate_search_queries(
    metadata: ArticleMetadata,
    client: OpenAI
) -> list[str]:
    """
    Uses the LLM to generate a set of targeted search queries from event metadata.
    Returns a list of query strings ready to pass to the web_search tool.
    """
    prompt = SEARCH_QUERY_SYSTEM_PROMPT.format(max_queries=MAX_SEARCH_QUERIES)

    user_content = f"""Event metadata:
- Summary: {metadata.summary}
- City: {metadata.city}
- Region: {metadata.region}
- Country: {metadata.country}
- Date range: {metadata.event_date_range}
- Key entities: {', '.join(metadata.entity_list)}

Generate {MAX_SEARCH_QUERIES} search queries to find local and regional news coverage of this event."""

    raw = api_chat(client, system=prompt, user=user_content, max_tokens=500)
    queries = json.loads(extract_json(raw))
    return queries[:MAX_SEARCH_QUERIES]


def run_web_searches(
    queries: list[str],
    metadata: ArticleMetadata,
    client: OpenAI
) -> list[CandidateArticle]:
    """
    Issues web searches via the OpenAI Responses API (web_search_preview tool),
    then parses results into CandidateArticle objects.

    The Responses API handles search execution automatically — no agentic loop needed.
    """
    query_list_str = "\n".join(f"  {i+1}. {q}" for i, q in enumerate(queries))
    search_instruction = f"""Search the web for LOCAL news coverage of this event. The event occurred in {metadata.country}.

Your goal is to find how news outlets IN {metadata.country.upper()} (and neighboring countries) covered this story.
PRIORITIZE: local news outlets, regional media, country-specific news sites, local-language reporting.
DEPRIORITIZE: CNN, BBC, Reuters, AP, NYT, Washington Post, The Guardian, and other major US/UK international outlets — their coverage is already known.

Run ALL of the following search queries and collect every distinct article found:
{query_list_str}

For every article found, list:
- Title
- Full URL
- Source/outlet name
- Country the outlet is based in
- 1-2 sentence excerpt

Include ALL articles found, especially those from {metadata.country} or the surrounding region."""

    print(f"      Issuing {len(queries)} web searches...")
    raw_results_text = api_search(client, search_instruction)

    # Parse the collected text into structured CandidateArticle objects
    print("      Parsing search results into candidate articles...")
    candidates = parse_search_results_to_candidates(raw_results_text, client)
    print(f"      Found {len(candidates)} unique candidate articles from web search.")
    return candidates


def parse_search_results_to_candidates(
    raw_results_text: str,
    client: OpenAI
) -> list[CandidateArticle]:
    """
    Uses the LLM to extract structured article metadata from raw search result text.
    Deduplicates by URL and assigns sequential IDs.
    """
    if not raw_results_text.strip():
        print("      [WARNING] No search result text to parse.")
        return []

    raw = api_chat(
        client,
        system=SEARCH_RESULT_PARSE_SYSTEM_PROMPT,
        user=f"Parse these search results:\n\n{raw_results_text[:8000]}",
        max_tokens=3000,
    )

    try:
        records = json.loads(extract_json(raw))
    except json.JSONDecodeError:
        # Model returned prose instead of JSON — ask it to convert explicitly
        print("      [WARNING] Response was not JSON. Retrying with strict JSON instruction...")
        print(f"      [DEBUG] Raw response was: {raw[:300]!r}")
        retry = api_chat(
            client,
            system="Convert the following text into a valid JSON array of news articles. "
                   "Each item must have: title, url, source_name, domain, snippet. "
                   "Return ONLY the JSON array, no other text.",
            user=raw[:6000],
            max_tokens=3000,
        )
        try:
            records = json.loads(extract_json(retry))
        except json.JSONDecodeError:
            print("      [WARNING] Retry also failed. Returning empty list.")
            return []

    seen_urls: set[str] = set()
    candidates: list[CandidateArticle] = []

    for i, rec in enumerate(records):
        url = rec.get("url", "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        # Extract domain from URL
        try:
            domain = urlparse(url).netloc.lower().replace("www.", "")
        except Exception:
            domain = rec.get("domain", "unknown")

        candidates.append(CandidateArticle(
            article_id=f"search_{i:03d}",
            title=rec.get("title", "Untitled"),
            url=url,
            source_name=rec.get("source_name", domain),
            domain=domain,
            mediarank_rank=None,  # looked up from file in Stage 2
            snippet=rec.get("snippet", "")
        ))

    return candidates[:MAX_CANDIDATE_POOL]


# ─────────────────────────────────────────────
# STAGE 1: ARTICLE METADATA EXTRACTION
# ─────────────────────────────────────────────

def extract_article_metadata(article_text: str, client: OpenAI) -> ArticleMetadata:
    """
    Extracts structured event metadata from the base article.
    These fields anchor all search queries and relevance scoring downstream.
    """
    system_prompt = """You are an information extraction assistant. Given a news article,
extract structured event metadata. Return ONLY valid JSON. No preamble, no markdown fences.

Output schema:
{
  "summary": "<1 sentence describing the specific incident or event>",
  "city": "<city where the event occurred, or null>",
  "region": "<state, province, or region, or null>",
  "country": "<country where the event occurred>",
  "event_date_range": "<ISO date or range, e.g. 2026-02-23 or 2026-02-22 to 2026-02-24>",
  "entity_list": ["<named person, organization, government, or armed group>"]
}"""

    raw = api_chat(client, system=system_prompt, user=f"Extract metadata:\n\n{article_text}", max_tokens=1000)
    data = json.loads(extract_json(raw))
    return ArticleMetadata(
        summary=data.get("summary", ""),
        city=data.get("city") or "",
        region=data.get("region") or "",
        country=data.get("country", ""),
        event_date_range=data.get("event_date_range", ""),
        entity_list=data.get("entity_list", [])
    )


# ─────────────────────────────────────────────
# STAGE 2: SOURCE QUALITY FILTERING
# ─────────────────────────────────────────────

def filter_candidates_by_source_quality(
    candidates: list[CandidateArticle],
    mediarank_lookup: dict[str, int]
) -> tuple[list[CandidateArticle], list[dict]]:
    """
    Applies the MediaRank hard gate using the pre-loaded local data file.
    Attaches ranks to candidates whose domains are found in the lookup.
    Sources with no rank data are allowed through.
    Results never shown to users.
    """
    for c in candidates:
        if c.mediarank_rank is None and c.domain in mediarank_lookup:
            c.mediarank_rank = mediarank_lookup[c.domain]

    passing, rejections = [], []
    for c in candidates:
        ok, reason = c.passes_source_filter()
        if ok:
            passing.append(c)
        else:
            rejections.append({
                "article_id": c.article_id,
                "source": c.source_name,
                "reason": reason
            })

    return passing, rejections


# ─────────────────────────────────────────────
# STAGE 3: LLM RELEVANCE SCORING — EXPLICIT CHECKLIST
# ─────────────────────────────────────────────

RELEVANCE_CHECKLIST = """
=== HARD CHECKS (answer Yes or No) ===
A "No" to any of Q1–Q4 sets hard_fail = true and score = 0.

Q1. Same incident: Does this article describe the SAME specific incident or event
    as the base article — not merely the same topic, region, or ongoing conflict?

Q2. Same location: Does this article refer to the same geographic location (city,
    region, or country) as the base article's event?

Q3. Same timeframe: Is this article reporting on events within ±7 days of the base
    article's event date? (Use judgment for ongoing events.)

Q4. Non-zero information delta: Does this article appear to add, confirm, or contest
    at least one piece of information relevant to the base article's event?

=== SOFT SCORING SIGNALS (answer Yes, Partial, or No + brief reason) ===

Q5. Shared named entities: Does this article reference the same key people,
    organizations, or armed groups as the base article?

Q6. Same event phase: Does this article describe the same phase of the event
    (e.g., both cover the immediate aftermath, not one the cause and one a
    follow-up weeks later)?

Q7. Geographic proximity of source: Is this article from an outlet based in the
    same country or region as the event?

Q8. Linguistic/cultural proximity: Is this article in the local language of the
    event country, or does it reflect a distinctly local perspective?

Q9. Headline signal strength: Does the headline directly reference the specific
    event, location, and/or key actors?
"""

RELEVANCE_SYSTEM_PROMPT = f"""You are scoring whether candidate articles are about the same specific event
as a base article. Work through the checklist for EACH candidate. Do not skip questions.

{RELEVANCE_CHECKLIST}

=== SCORING RULES ===
If ANY of Q1–Q4 is "No": hard_fail = true, score = 0, label = "different_event".
If all Q1–Q4 are "Yes":
  Base score: 60
  Q5 Yes → +15, Partial → +7, No → +0
  Q6 Yes → +10, Partial → +5, No → +0
  Q7 Yes → +8, No → +0
  Q8 Yes → +5, No → +0
  Q9 Yes → +2, No → +0
  Maximum possible: 100

Labels:
  "same_event"      → score ≥ 75, hard_fail = false
  "related_context" → score 60–74, hard_fail = false
  "different_event" → hard_fail = true OR score < 60
  "uncertain"       → score 60–74 AND relevance cannot be determined from title/snippet alone

Return ONLY a valid JSON array. No preamble, no markdown fences.

Each item:
{{
  "id": "...",
  "score_0_100": <integer>,
  "label": "same_event" | "related_context" | "different_event" | "uncertain",
  "hard_fail": true | false,
  "need_snippet_or_fulltext": true | false,
  "checklist": {{
    "Q1_same_incident":        "<Yes/No + reason>",
    "Q2_same_location":        "<Yes/No + reason>",
    "Q3_same_timeframe":       "<Yes/No + reason>",
    "Q4_nonzero_delta":        "<Yes/No + reason>",
    "Q5_shared_entities":      "<Yes/Partial/No + reason>",
    "Q6_same_event_phase":     "<Yes/Partial/No + reason>",
    "Q7_geographic_proximity": "<Yes/No + reason>",
    "Q8_linguistic_proximity": "<Yes/No + reason>",
    "Q9_headline_signal":      "<Yes/No + reason>"
  }}
}}"""


def score_candidate_relevance(
    base_metadata: ArticleMetadata,
    candidates: list[CandidateArticle],
    client: OpenAI
) -> list[RelevanceResult]:
    """
    Scores all candidates against the explicit 9-question checklist.
    Includes title AND snippet in the payload so the LLM has more signal.
    All answers are stored — the decision is fully auditable.
    """
    candidate_payload = [
        {
            "id": c.article_id,
            "title": c.title,
            "source": c.source_name,
            "snippet": c.snippet
        }
        for c in candidates
    ]

    user_prompt = f"""Base article event record:
- Event summary: {base_metadata.summary}
- Where: {base_metadata.city}, {base_metadata.region}, {base_metadata.country}
- When: {base_metadata.event_date_range}
- Key entities: {', '.join(base_metadata.entity_list)}

Candidate articles (title + snippet from web search):
{json.dumps(candidate_payload, indent=2, ensure_ascii=False)}

Score each candidate using the full checklist. Return JSON array only."""

    raw = api_chat(client, system=RELEVANCE_SYSTEM_PROMPT, user=user_prompt, max_tokens=4000, model=OPENAI_MODEL)
    results_data = json.loads(extract_json(raw))

    return [
        RelevanceResult(
            article_id=item["id"],
            score=item["score_0_100"],
            label=item["label"],
            hard_fail=item.get("hard_fail", False),
            checklist_answers=item.get("checklist", {}),
            need_full_text=item.get("need_snippet_or_fulltext", False)
        )
        for item in results_data
    ]


# ─────────────────────────────────────────────
# STAGE 4: ARTICLE SELECTION (up to 5)
# ─────────────────────────────────────────────

def select_articles(
    candidates: list[CandidateArticle],
    relevance_results: list[RelevanceResult],
    max_count: int = MAX_DISPLAY_ARTICLES
) -> list[dict]:
    """
    Selects up to max_count articles from those that passed relevance scoring.

    Ranking:
      1. Filter: hard_fail = False AND score >= RELEVANCE_SCORE_THRESHOLD.
      2. Sort by score descending.
      3. Tiebreaker: prefer Q7 (local outlet) and Q8 (local language) = Yes.
      4. Return top max_count.
    """
    candidate_map = {c.article_id: c for c in candidates}

    eligible = [
        r for r in relevance_results
        if not r.hard_fail and r.score >= RELEVANCE_SCORE_THRESHOLD
    ]

    def effective_score(r: RelevanceResult) -> int:
        """Boost score for local/regional sources so they rank above same-score foreign outlets."""
        geo  = 20 if "Yes" in r.checklist_answers.get("Q7_geographic_proximity", "") else 0
        ling = 10 if "Yes" in r.checklist_answers.get("Q8_linguistic_proximity", "") else 0
        return r.score + geo + ling

    eligible.sort(key=effective_score, reverse=True)

    output = []
    for r in eligible[:max_count]:
        c = candidate_map.get(r.article_id)
        if not c:
            continue
        output.append({
            "article_id":      c.article_id,
            "source_name":     c.source_name,
            "title":           c.title,
            "url":             c.url,
            "snippet":         c.snippet,
            "relevance_score": r.score,
            "effective_score": effective_score(r),
            "label":           r.label,
            "checklist":       r.checklist_answers
        })

    return output


# ─────────────────────────────────────────────
# MAIN PIPELINE ORCHESTRATOR
# ─────────────────────────────────────────────

def run_clearframe_pipeline(
    base_article_text: str,
    mediarank_filepath: str = "data/mediarank_rankings.csv",
    api_key: str | None = None
) -> dict:
    """
    Full self-contained ClearFrame pipeline (v3).

    Provide only the base article text — the pipeline finds everything else.

    Stages:
      0. Generate search queries from event metadata; run web searches; collect candidates.
      1. Extract structured event metadata from the base article.
      2. Load MediaRank data; filter candidates by source quality (backend only).
      3. Score remaining candidates using the explicit 9-question relevance checklist.
      4. Select up to 5 articles ranked by relevance score.

    Args:
        base_article_text:  Full text of the article the user is reading.
        mediarank_filepath:  Path to MediaRank CSV. Export from media-rank.com/filter.
                             Pipeline runs without it (no MediaRank filter applied).
        api_key:            OpenAI API key. Falls back to OPENAI_API_KEY env var.

    Returns dict with keys:
        metadata           — extracted event fields from the base article
        selected_articles  — up to 5 articles to show the user
        rejection_log      — sources rejected by the MediaRank filter
        relevance_debug    — full checklist answers for every scored candidate
        search_queries     — the queries that were issued in Stage 0
    """
    client = OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))

    # ── Stage 1: Extract base article metadata ────────────────────────────
    print("[1/4] Extracting base article metadata...")
    metadata = extract_article_metadata(base_article_text, client)
    print(f"      Summary  : {metadata.summary}")
    print(f"      Location : {metadata.city}, {metadata.region}, {metadata.country}")
    print(f"      Date     : {metadata.event_date_range}")
    print(f"      Entities : {', '.join(metadata.entity_list)}")

    # ── Stage 0: Generate queries and search the web ──────────────────────
    # (Numbered 0 but run after metadata extraction, which it depends on.)
    print("\n[0/4] Generating search queries and finding candidate articles...")
    queries = generate_search_queries(metadata, client)
    print(f"      Generated {len(queries)} search queries:")
    for q in queries:
        print(f"        • {q}")

    raw_candidates = run_web_searches(queries, metadata, client)

    if not raw_candidates:
        print("      [WARNING] Web search returned no candidates.")
        return {
            "metadata": vars(metadata),
            "selected_articles": [],
            "rejection_log": [],
            "relevance_debug": [],
            "search_queries": queries
        }

    # ── Stage 2: Source quality filter ───────────────────────────────────
    print(f"\n[2/4] Filtering {len(raw_candidates)} candidates by source quality...")
    mediarank_lookup = load_mediarank_data(mediarank_filepath)
    qualified, rejections = filter_candidates_by_source_quality(raw_candidates, mediarank_lookup)
    print(f"      {len(qualified)} passed  |  {len(rejections)} rejected")
    for r in rejections:
        print(f"        ✗ {r['source']}: {r['reason']}")

    if not qualified:
        return {
            "metadata": vars(metadata),
            "selected_articles": [],
            "rejection_log": rejections,
            "relevance_debug": [],
            "search_queries": queries
        }

    # ── Stage 3: Relevance scoring ────────────────────────────────────────
    print(f"\n[3/4] Scoring {len(qualified)} candidates for relevance...")
    relevance_results = score_candidate_relevance(metadata, qualified, client)

    for r in relevance_results:
        status = "PASS" if (not r.hard_fail and r.score >= RELEVANCE_SCORE_THRESHOLD) else "FAIL"
        print(f"      [{status}] {r.article_id} — score: {r.score:>3}  label: {r.label}")

    # ── Stage 4: Final selection ──────────────────────────────────────────
    print(f"\n[4/4] Selecting up to {MAX_DISPLAY_ARTICLES} articles...")
    selected = select_articles(qualified, relevance_results, max_count=MAX_DISPLAY_ARTICLES)
    print(f"      {len(selected)} article(s) selected.\n")

    # Print a clean summary for quick inspection
    print("=" * 60)
    print("SELECTED ARTICLES")
    print("=" * 60)
    for i, a in enumerate(selected, 1):
        print(f"  {i}. [{a['relevance_score']}] {a['source_name']} — {a['title']}")
        print(f"     {a['url']}")
    print("=" * 60)

    return {
        "metadata": {
            "summary":     metadata.summary,
            "location":    f"{metadata.city}, {metadata.region}, {metadata.country}",
            "date_range":  metadata.event_date_range,
            "entities":    metadata.entity_list
        },
        "selected_articles": selected,
        "rejection_log":     rejections,
        "relevance_debug": [
            {
                "article_id": r.article_id,
                "score":      r.score,
                "label":      r.label,
                "hard_fail":  r.hard_fail,
                "checklist":  r.checklist_answers
            }
            for r in relevance_results
        ],
        "search_queries": queries
    }


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    # Paste any news article text here to run the full pipeline.
    # The LLM will search the web, score candidates, and return the top 5.
    BASE_ARTICLE = """
    Trump Casts a Shadow Over One of Mexico's Deadliest States

    In Sinaloa, a state of three million people that has been a stronghold of the Sinaloa
    Cartel for decades, residents are about 20 months into a war that began when the cartel
    fractured into two. President Trump wants to strike cartels inside Mexico. In Sinaloa
    State, some residents said they were willing to entertain U.S. intervention.

    On the whole, Mexicans do not support Trump's proposal of U.S. military strikes against
    the country's powerful cartels — nearly eight in 10 opposed the idea in a national poll
    last month. But in Sinaloa, many residents said they were desperate for peace at
    whatever cost, even if it meant a U.S. military intervention.

    Daily life in Culiacán, the capital of Sinaloa, has been upended since July 2024 when
    one of El Chapo's sons betrayed El Mayo, splitting the Sinaloa Cartel. At the height of
    the violence, people barricaded themselves indoors for weeks. Bodies were dumped along
    roadsides, gun battles erupted in upscale neighborhoods and burned-out tractor-trailers
    blocked highways. Just in January, two lawmakers were shot after leaving the State
    Congress. Ten workers from a Canadian-owned gold mine were abducted; seven bodies were
    later found.

    Sinaloa state lost nearly 10 percent of its GDP in 2024 and 2025. More than 2,000
    companies have shut down. Hotel, tourism, and restaurant sales have dropped 50 percent.

    Mexican security forces, with more than 12,000 soldiers dispatched by President
    Claudia Sheinbaum, have arrested dozens of high-ranking cartel members. Last month,
    security forces killed Rubén Oseguera Cervantes (El Mencho), leader of the Jalisco New
    Generation Cartel, igniting retaliatory violence across at least 20 states.

    On Saturday, Trump mocked President Sheinbaum at a summit of 12 Latin American
    countries focused on defeating cartels, saying she had refused his help. Sheinbaum
    responded: "It's good that President Trump publicly says that when he proposed sending
    the U.S. military into Mexico, we said no. Because that's the truth."

    Cartel members described stockpiling weapons, installing lookouts scanning the skies,
    and buying rocket-propelled grenades and anti-drone systems costing up to $40,000 each.

    Published: 2026-03-11. Source: The New York Times.
    Authors: Paulina Villegas, Jack Nicas. Reporting from Culiacán, Mexico.
    """

    result = run_clearframe_pipeline(
        base_article_text=BASE_ARTICLE,
        mediarank_filepath="data/mediarank_rankings.csv"  # optional — skip if file not present
    )

    # Full JSON output for debugging
    print("\nFULL OUTPUT (JSON):")
    print(json.dumps(result, indent=2, ensure_ascii=False))