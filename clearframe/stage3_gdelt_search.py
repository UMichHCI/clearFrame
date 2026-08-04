import time

import requests

from .config import COUNTRY_FALLBACK, FALLBACK_DEFAULT, GDELT_URL

_gdelt_request_count = 0
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
        print(f"  [DEBUG] Rate limited â€” waiting {RETRY_WAIT}s before retry...")
        time.sleep(RETRY_WAIT)

    if response is None:
        print("  [WARNING] GDELT request failed on every attempt â€” returning no results.")
        return {}

    try:
        return response.json()
    except Exception:
        print("[WARNING] GDELT did not return valid JSON:")
        print(response.text[:500])
        return {}

