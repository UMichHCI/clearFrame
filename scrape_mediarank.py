"""
One-time scraper to build a comprehensive MediaRank CSV from media-rank.com/filter.
Iterates through each country filter to capture sources beyond the default top-500.
Deduplicates by domain, keeping the best (lowest) rank for each.
"""

import requests
from bs4 import BeautifulSoup
import csv
import time

COUNTRIES = [
    "Argentina", "Australia", "Austria", "Bangladesh", "Belgium", "Botswana",
    "Brazil", "Bulgaria", "Canada", "Chile", "China", "Colombia", "Cuba",
    "Czech Republic", "Egypt", "Ethiopia", "France", "Germany", "Ghana",
    "Greece", "Hong Kong", "Hungary", "India", "Indonesia", "Ireland",
    "Israel", "Italy", "Japan", "Kenya", "Korea", "Latvia", "Lebanon",
    "Lithuania", "Malaysia", "Mexico", "Namibia", "Netherlands", "New Zealand",
    "Norway", "Pakistan", "Peru", "Philippines", "Poland", "Portugal",
    "Romania", "Russia", "Senegal", "Serbia", "Singapore", "Slovakia",
    "Slovenia", "South Africa", "Spain", "Sweden", "Switzerland", "Taiwan",
    "Tanzania", "Thailand", "Turkey", "Uganda", "Ukraine",
    "United Arab Emirates", "United Kingdom", "United States", "Venezuela",
    "Vietnam", "Zimbabwe"
]

URL = "https://www.media-rank.com/filter"

def parse_table(soup: BeautifulSoup) -> list[dict]:
    """Parse the rftable: domain is col 6, rank is col 5 (0-indexed)."""
    table = soup.find("table", id="rftable")
    if not table:
        return []

    rows = []
    for tr in table.find_all("tr")[1:]:  # skip header
        cells = tr.find_all("td")
        if len(cells) >= 7:
            domain = cells[6].get_text(strip=True).lower().replace("www.", "")
            try:
                rank = int(cells[5].get_text(strip=True).replace(",", ""))
            except ValueError:
                continue
            if domain:
                rows.append({"domain": domain, "rank": rank})

    return rows


def scrape_country(country: str, session: requests.Session) -> list[dict]:
    """Scrape all sources for a given country from the filter page."""
    try:
        resp = session.get(URL, params={"country": country}, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [ERROR] Failed to fetch {country}: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    return parse_table(soup)


def main():
    # domain -> best rank seen
    all_sources: dict[str, int] = {}

    session = requests.Session()
    session.headers.update({
        "User-Agent": "ClearFrame-Academic-Research/1.0 (media ranking dataset collection)"
    })

    # First grab the default "All" view
    print("Scraping: All (default top 500)...")
    try:
        resp = session.get(URL, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for row in parse_table(soup):
            all_sources[row["domain"]] = row["rank"]
        print(f"  Found {len(all_sources)} sources from default view")
    except requests.RequestException as e:
        print(f"  [ERROR] Failed default fetch: {e}")

    # Now iterate through each country
    for i, country in enumerate(COUNTRIES, 1):
        print(f"Scraping: {country} ({i}/{len(COUNTRIES)})...")
        rows = scrape_country(country, session)
        new_count = 0
        for row in rows:
            d, r = row["domain"], row["rank"]
            if d not in all_sources or r < all_sources[d]:
                if d not in all_sources:
                    new_count += 1
                all_sources[d] = r
        print(f"  Got {len(rows)} rows, {new_count} new unique domains (total: {len(all_sources)})")
        time.sleep(0.5)  # be polite

    # Sort by rank and write CSV
    sorted_sources = sorted(all_sources.items(), key=lambda x: x[1])

    output_path = "data/mediarank_rankings.csv"
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["domain", "rank"])
        for domain, rank in sorted_sources:
            writer.writerow([domain, rank])

    print(f"\nDone! Wrote {len(sorted_sources)} unique sources to {output_path}")
    if sorted_sources:
        print(f"Rank range: {sorted_sources[0][1]} to {sorted_sources[-1][1]}")


if __name__ == "__main__":
    main()
