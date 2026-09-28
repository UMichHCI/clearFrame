import time

import requests

from .config import COUNTRY_FALLBACK, FALLBACK_DEFAULT, GDELT_URL

_gdelt_request_count = 0


class GDELTSearchError(RuntimeError):
    """Raised when GDELT does not return a valid successful response."""


def normalize_country(text: str) -> str:
    return str(text).strip().lower().replace(" ", "")


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
    query_terms should be the location+terms portion of the query only â€” no sourcecountry clause.
    """
    fallback_query = f"{query_terms} AND domain:{fallback_domain}"
    return search_gdelt(fallback_query, startdatetime=startdatetime,
                        enddatetime=enddatetime, maxrecords=maxrecords)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# STAGE 3 â€” GDELT SEARCH
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

    # Flat 5s wait between every retry â€” both for rate limits (429) and for
    # request-level failures (read timeout, connection reset). GDELT is often
    # slow to hand off the connection, so a timed-out request is retried rather
    # than allowed to crash the pipeline. Fixed 5s keeps total wait bounded and
    # avoids the long tail of exponential backoff.
    RETRY_WAIT = 5
    response = None
    last_request_error = None
    for attempt in range(5):
        try:
            response = requests.get(GDELT_URL, params=params, timeout=30)
        except requests.exceptions.RequestException as e:
            last_request_error = e
            print(f"  [DEBUG] GDELT request failed ({e.__class__.__name__}) on attempt {attempt + 1}.")
            if attempt < 4:
                print(f"  [DEBUG] Waiting {RETRY_WAIT}s before retry...")
                time.sleep(RETRY_WAIT)
            continue

        print(f"  [DEBUG] GDELT HTTP status: {response.status_code} (attempt {attempt + 1})")
        if response.status_code == 429:
            if attempt < 4:
                print(f"  [DEBUG] Rate limited â€” waiting {RETRY_WAIT}s before retry...")
                time.sleep(RETRY_WAIT)
            continue
        if response.status_code != 200:
            raise GDELTSearchError(
                f"GDELT returned HTTP {response.status_code}."
            )
        break

    if response is None:
        detail = f" ({last_request_error})" if last_request_error else ""
        raise GDELTSearchError(
            f"GDELT request failed on every attempt{detail}."
        )

    if response.status_code == 429:
        raise GDELTSearchError(
            "GDELT rate limiting persisted after 5 attempts."
        )

    try:
        payload = response.json()
    except Exception as exc:
        detail = response.text[:500].strip()
        raise GDELTSearchError(
            f"GDELT did not return valid JSON: {detail}"
        ) from exc

    if not isinstance(payload, dict):
        raise GDELTSearchError("GDELT returned an unexpected JSON response.")
    return payload


def search_gdelt_balanced(
    query: str,
    query_countries: list[str],
    startdatetime: str,
    enddatetime: str,
    maxrecords_per_country: int = 10,
    overfetch_factor: int = 3,
) -> list[dict]:
    """
    Runs one combined GDELT request and retains an overfetched country pool.

    Diversity and the final per-country cap are applied later, after full-text
    retrieval and topical filtering. Keeping the overflow here provides enough
    alternatives to replace duplicates and repeated outlets.
    Returns a flat, URL-deduplicated article list with a `query_country` field
    matching the article's sourcecountry when it is one of the query countries.
    """
    country_lookup: dict[str, str] = {}
    for country in query_countries:
        normalized = normalize_country(country)
        if normalized and normalized not in country_lookup:
            country_lookup[normalized] = country

    if not country_lookup:
        return []

    maxrecords = maxrecords_per_country * len(country_lookup) * max(1, overfetch_factor)
    print(f"      Combined GDELT request: max {maxrecords} "
          f"({maxrecords_per_country} per country target, overfetch x{max(1, overfetch_factor)})")

    results = search_gdelt(
        query,
        startdatetime=startdatetime,
        enddatetime=enddatetime,
        maxrecords=maxrecords,
    )

    pool_limit_per_country = maxrecords_per_country * max(1, overfetch_factor)
    articles: list[dict] = []
    seen_urls: set[str] = set()
    counts: dict[str, int] = {country: 0 for country in country_lookup}

    for raw_article in results.get("articles", []):
        if not isinstance(raw_article, dict):
            continue

        normalized_country = normalize_country(raw_article.get("sourcecountry", ""))
        if normalized_country not in country_lookup:
            continue
        if counts[normalized_country] >= pool_limit_per_country:
            continue

        url = str(raw_article.get("url", "")).strip()
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)

        article = dict(raw_article)
        article["query_country"] = country_lookup[normalized_country]
        articles.append(article)
        counts[normalized_country] += 1

    for normalized, original in country_lookup.items():
        print(f"        {original}: {counts[normalized]} candidate(s) retained for diversity selection")

    return articles

