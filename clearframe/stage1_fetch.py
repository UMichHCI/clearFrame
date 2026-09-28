from datetime import datetime, timezone

import requests
import trafilatura
_SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

def get_article_text(url: str) -> tuple[str, datetime, str]:
    """
    Fetches and extracts article text, publication date, and title.
    Returns (text, pub_date, title). Falls back to ("", today, "") on failure.
    """
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        response = requests.get(url, headers=_SCRAPE_HEADERS, timeout=20)
        response.raise_for_status()
        html = response.text
        text = trafilatura.extract(html, include_comments=False, include_tables=False)
        if not text:
            print(f"  [WARNING] trafilatura returned empty content for: {url}")
            return "", today, ""

        pub_date = today
        article_title = ""
        try:
            metadata = trafilatura.extract_metadata(html)
            if metadata:
                article_title = str(metadata.title or "").strip()
                if metadata.date:
                    parsed = datetime.fromisoformat(metadata.date.split("T")[0])
                    pub_date = parsed.replace(tzinfo=timezone.utc)
        except Exception:
            pass

        if pub_date == today:
            print(f"  [WARNING] No publication date found â€” defaulting to today.")
        else:
            print(f"      Publication date: {pub_date.strftime('%Y-%m-%d')}")

        return text[:8000], pub_date, article_title
    except Exception as e:
        print(f"  [WARNING] trafilatura failed for {url}: {e}")
        return "", today, ""

