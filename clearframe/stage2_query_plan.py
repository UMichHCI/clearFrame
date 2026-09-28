import json
from datetime import datetime, timedelta, timezone

from openai import OpenAI

from .llm import api_chat, extract_json
from .prompts import QUERY_PLAN_SYSTEM


ARTICLE_TYPES = {
    "breaking_news",
    "ongoing_situation",
    "economics_policy",
    "historical",
    "human_interest",
    "mixed",
}

# These entities can be actors in a story, but they are not publishing countries
# accepted by GDELT's sourcecountry operator. Keep this deterministic because an
# LLM prompt alone cannot guarantee a valid query plan.
NON_COUNTRY_ACTORS = {
    "africanunion": "African Union",
    "arableague": "Arab League",
    "asean": "ASEAN",
    "brics": "BRICS",
    "europeancommission": "European Commission",
    "europeanparliament": "European Parliament",
    "europeanunion": "European Union",
    "eu": "European Union",
    "g7": "G7",
    "g20": "G20",
    "gcc": "Gulf Cooperation Council",
    "gulfcooperationcouncil": "Gulf Cooperation Council",
    "nato": "NATO",
    "unitednations": "United Nations",
}


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


def find_non_country_actors(countries: list[str]) -> list[str]:
    """Return named organizations that cannot be GDELT source countries."""
    invalid = []
    for country in countries:
        label = NON_COUNTRY_ACTORS.get(normalize_country(country))
        if label and label not in invalid:
            invalid.append(label)
    return invalid


def clean_plan(plan: dict, max_terms: int = 4) -> dict:
    location            = str(plan.get("location", "")).strip()
    source_country      = str(plan.get("source_country", "")).strip()
    original_source_country = str(plan.get("original_source_country", "")).strip()
    article_type        = str(plan.get("article_type", "")).strip().lower()
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
    if article_type not in ARTICLE_TYPES:
        raise ValueError(f"Query plan: invalid article_type '{article_type}'.")
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
            "terms": terms, "article_type": article_type,
            "window_days_before": window_days_before,
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



