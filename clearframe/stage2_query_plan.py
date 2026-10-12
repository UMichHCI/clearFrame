import json
from datetime import datetime, timezone

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


def make_query_plan(
    article_text: str, source_url: str, client: OpenAI,
    publication_date: datetime | None = None,
) -> dict:
    publication_context = (
        publication_date.strftime("%Y-%m-%d") if publication_date else "unknown"
    )
    context = (
        f"Source URL:\n{source_url}\n\n"
        f"Publication date (context only; may be a fetch-time fallback): {publication_context}\n"
        f"Current date (UTC): {datetime.now(timezone.utc):%Y-%m-%d}\n\n"
        f"Article:\n{article_text}"
    )
    correction = ""
    for attempt in range(3):
        raw = api_chat(
            client,
            system=QUERY_PLAN_SYSTEM,
            user=context + correction,
            max_tokens=700,
            response_format={"type": "json_object"},
        )
        try:
            plan = json.loads(extract_json(raw))
            if not isinstance(plan, dict):
                raise ValueError("Query plan must be a JSON object.")
            clean_plan(plan)
            return plan
        except ValueError as exc:
            if attempt == 2:
                raise ValueError(f"Query plan remained invalid after 3 attempts: {exc}") from exc
            print(f"      [WARNING] Invalid query plan: {exc} Retrying ({attempt + 2}/3)...")
            correction = (
                f"\n\nYour previous response:\n{raw}\n\n"
                f"Validation error: {exc}\n"
                "Return a corrected complete JSON plan. Supply both coverage dates "
                "as YYYY-MM-DD; neither may be null or missing. Always estimate the "
                "reporting period using the article context and supplied dates. "
                "Explain uncertainty and any approximate timing in coverage_period_reason."
            )


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


def parse_coverage_date(value: str) -> datetime:
    """Validate the model's date format and return midnight UTC."""
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if parsed.strftime("%Y-%m-%d") != value:
            raise ValueError
        return parsed
    except (TypeError, ValueError):
        raise ValueError("Query plan: coverage dates must use YYYY-MM-DD.") from None


def clean_plan(plan: dict, max_terms: int = 4) -> dict:
    location            = str(plan.get("location", "")).strip()
    source_country      = str(plan.get("source_country", "")).strip()
    original_source_country = str(plan.get("original_source_country", "")).strip()
    article_type        = str(plan.get("article_type", "")).strip().lower()
    coverage_start_date = plan.get("coverage_start_date")
    coverage_end_date = plan.get("coverage_end_date")
    coverage_period_reason = str(plan.get("coverage_period_reason") or "").strip()
    if not coverage_period_reason:
        raise ValueError("Query plan: coverage_period_reason is empty.")
    if coverage_start_date is None or coverage_end_date is None:
        raise ValueError("Query plan: both coverage dates are required and must not be null.")
    start_date = parse_coverage_date(coverage_start_date)
    end_date = parse_coverage_date(coverage_end_date)
    if start_date > end_date:
        raise ValueError("Query plan: coverage_start_date is after coverage_end_date.")
    if end_date.date() > datetime.now(timezone.utc).date():
        raise ValueError("Query plan: coverage dates cannot be in the future.")

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
            "coverage_start_date": coverage_start_date,
            "coverage_end_date": coverage_end_date,
            "coverage_period_reason": coverage_period_reason}


def build_gdelt_query(
    terms: list[str], query_countries: list[str],
    coverage_start_date: str, coverage_end_date: str,
) -> tuple[str, str, str]:
    """
    Builds a GDELT DOC API query from topic terms and publishing countries.
    Location metadata is not a required text match.
    Returns (query, startdatetime, enddatetime).
    GDELT datetime format: YYYYMMDDHHMMSS
    """
    today      = datetime.now(timezone.utc)
    start_date = parse_coverage_date(coverage_start_date)
    # Include the whole final day, capped at the current instant.
    end_date = min(
        parse_coverage_date(coverage_end_date).replace(hour=23, minute=59, second=59),
        today,
    )
    if start_date > end_date:
        raise ValueError("Query plan: coverage period has no searchable dates.")

    tparts = " OR ".join(quote_if_needed(t) for t in terms)
    countries = []
    for country in query_countries:
        ctry = normalize_country(country)
        if ctry and ctry not in countries:
            countries.append(ctry)
    cparts = " OR ".join(f"sourcecountry:{ctry}" for ctry in countries)
    query  = f"({tparts}) AND ({cparts})"

    start_str = start_date.strftime("%Y%m%d%H%M%S")
    end_str   = end_date.strftime("%Y%m%d%H%M%S")
    return query, start_str, end_str

