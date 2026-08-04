import json
from datetime import datetime, timedelta, timezone

from openai import OpenAI

from .llm import api_chat, extract_json
QUERY_PLAN_SYSTEM = """
You create ONE broad GDELT query plan for finding related news articles.
Respond with a JSON object only: no explanation, no markdown, no extra keys.

The JSON must have exactly these seven top-level keys:
  "location"                - the city, region, battlefield, or named place where the event is centered (string, never empty)
  "source_country"          - the main event country containing that location, or the country most directly affected (string, never empty)
  "original_source_country" - the publishing country of the article URL/outlet the user supplied (string, never empty)
  "actor_countries"         - 2 to 5 countries directly involved in the event as actors, affected parties, or decision-makers (array of strings)
  "terms"                   - 3 to 4 short broad topic keywords (array of strings)
  "window_days_before"      - integer: how many days before the publication date to search
  "window_days_after"       - integer: how many days after the publication date to search

The goal is to find coverage from related countries other than the original
source article's publishing country. Infer actor_countries from the article text
when possible. If the text implies but does not explicitly name all major actors,
use your background knowledge to include directly associated countries.

Example: for a U.S. outlet article about the war in Ukraine, original_source_country
should be "United States", source_country should usually be "Ukraine", and
actor_countries should include "Ukraine" and "Russia". Include "United States" in
actor_countries only if U.S. decisions, weapons, funding, officials, or institutions
are direct parts of the specific story; the query builder will still exclude it
because it is the original source country.

Choose window_days_before and window_days_after based on the article type:
  Breaking news         -> 14 before, 14 after
  Ongoing situation     -> 90 before, 90 after
  Historical/background -> 365 before, 180 after
  Economics/policy      -> 180 before, 90 after
  Human interest        -> 60 before, 60 after
  Uncertain             -> 90 before, 90 after

Example output:
{
  "location": "Puerto Vallarta",
  "source_country": "Mexico",
  "original_source_country": "United States",
  "actor_countries": ["Mexico"],
  "terms": ["cartel", "violence", "drug war"],
  "window_days_before": 14,
  "window_days_after": 14
}

Rules:
- location, source_country, and original_source_country must never be empty strings
- actor_countries must include source_country unless source_country is only a proxy for a broader region
- actor_countries should be direct country actors, not news outlet locations
- do not include the base article's publishing country merely because the outlet is based there
- terms should be broad for high recall and should not be country names already listed in actor_countries
"""

def make_query_plan(article_text: str, source_url: str, client: OpenAI) -> dict:
    raw = api_chat(
        client,
        system=QUERY_PLAN_SYSTEM,
        user=f"Source URL:\n{source_url}\n\nArticle:\n{article_text}",
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
    original_source_country = str(plan.get("original_source_country", "")).strip()
    window_days_before  = int(plan.get("window_days_before", 90))
    window_days_after   = int(plan.get("window_days_after", 90))

    actor_countries = []
    seen_countries = set()
    raw_actor_countries = plan.get("actor_countries", [])
    if not isinstance(raw_actor_countries, list):
        raw_actor_countries = []
    for country in [source_country, *raw_actor_countries]:
        country = str(country).strip()
        key = normalize_country(country)
        if country and key not in seen_countries:
            actor_countries.append(country)
            seen_countries.add(key)
    actor_countries = actor_countries[:5]

    original_source_key = normalize_country(original_source_country)
    query_countries = [
        country for country in actor_countries
        if normalize_country(country) != original_source_key
    ]
    actor_country_keys = {normalize_country(country) for country in actor_countries}

    terms = []
    for term in plan.get("terms", []):
        term = str(term).strip()
        if (term
                and term.lower() != location.lower()
                and term.lower() != source_country.lower()
                and normalize_country(term) not in actor_country_keys
                and term not in terms):
            terms.append(term)
    terms = terms[:max_terms]

    if not location:
        raise ValueError("Query plan: location is empty.")
    if not source_country:
        raise ValueError("Query plan: source_country is empty.")
    if not original_source_country:
        raise ValueError("Query plan: original_source_country is empty.")
    if not actor_countries:
        raise ValueError("Query plan: actor_countries is empty.")
    if not query_countries:
        raise ValueError(
            "Query plan: no actor_countries remain after excluding original_source_country."
        )
    if not terms:
        raise ValueError("Query plan: no usable terms.")

    return {"location": location, "source_country": source_country,
            "original_source_country": original_source_country,
            "actor_countries": actor_countries,
            "query_countries": query_countries,
            "terms": terms, "window_days_before": window_days_before,
            "window_days_after": window_days_after}


def build_gdelt_query(
    location: str, terms: list[str], query_countries: list[str],
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
    countries = []
    for country in query_countries:
        ctry = normalize_country(country)
        if ctry and ctry not in countries:
            countries.append(ctry)
    cparts = " OR ".join(f"sourcecountry:{ctry}" for ctry in countries)
    query  = f"{loc} AND ({tparts}) AND ({cparts})"

    start_str = start_date.strftime("%Y%m%d%H%M%S")
    end_str   = end_date.strftime("%Y%m%d%H%M%S")
    return query, start_str, end_str


