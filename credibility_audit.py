"""
credibility_audit.py
====================
Queries ChatGPT on the credibility of ~100 non-western news sources drawn from
data/mediarank_rankings.csv (South America, Asia, Africa) and writes results to
data/credibility_audit.csv.

Usage:
    python credibility_audit.py

Requires OPENAI_API_KEY in .env or environment.
"""

import csv
import os
import time
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ---------------------------------------------------------------------------
# Source selection
# ---------------------------------------------------------------------------

SOUTH_AMERICA = {
    "BRA","ARG","CHL","COL","PER","VEN","URY","ECU","BOL","PRY","GUY","SUR",
    "CUB","HTI","JAM","TTO","DOM",
}
AFRICA = {
    "ZAF","NGA","WAN","KEN","GHA","ETH","TZA","ZWE","ZMB","UGA","SEN","MOZ","MWI",
    "BWA","NAM","MUS","CMR","CIV","MLI","BFA","NER","TCD","SDN","SSD","ERI","DJI",
    "SOM","RWA","BDI","COD","COG","GAB","GNQ","AGO","LSO","SWZ","MDG","COM","DZA",
    "MAR","TUN","LBY","EGY",
}
ASIA = {
    "IND","CHN","JPN","KOR","IDN","PHL","TUR","MYS","SGP","PAK","VNM","TWN",
    "BGD","LKA","NPL","MMR","KHM","LAO","THA","MNG","AZE","KAZ","UZB","GEO",
    "ARM","IRN","IRQ","SAU","ARE","QAT","KWT","BHR","OMN","YEM","JOR","LBN","SYR","AFG",
}
NON_WESTERN = SOUTH_AMERICA | AFRICA | ASIA

# Domains that are not news outlets and should be excluded
NON_NEWS_DOMAINS = {
    "surveymonkey.com", "gettyimages.com", "shutterstock.com", "istockphoto.com",
    "alamy.com", "depositphotos.com", "dreamstime.com", "123rf.com",
    "academia.edu", "researchgate.net", "slideshare.net",
    "facebook.com", "twitter.com", "instagram.com", "youtube.com", "tiktok.com",
    "wikipedia.org", "wikimedia.org", "google.com", "amazon.com",
}

KNOWN_TOPICS = {"GENERAL","BUSINESS","TECHNOLOGY","HEALTH","SCIENCE","ENTERTAINMENT","SPORTS"}
ALLOCATIONS = {
    "GENERAL": 35,
    "BUSINESS": 15,
    "TECHNOLOGY": 12,
    "HEALTH": 10,
    "SCIENCE": 8,
    "ENTERTAINMENT": 8,
    "SPORTS": 8,
    "OTHER": 4,
}

DATA_DIR = Path(__file__).parent / "data"
INPUT_CSV = DATA_DIR / "mediarank_rankings.csv"
OUTPUT_CSV = DATA_DIR / "credibility_audit.csv"


def select_sources() -> list[dict]:
    buckets: dict[str, list[dict]] = {k: [] for k in ALLOCATIONS}

    with open(INPUT_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["Country Code"] not in NON_WESTERN:
                continue
            # Skip rows with no outlet name or known non-news domains
            name = row["Outlet Name"].strip()
            if not name or name.lower() == "nan" or row["Domain"] in NON_NEWS_DOMAINS:
                continue
            try:
                row["_score"] = float(row["MediaRank Score"])
            except ValueError:
                row["_score"] = 0.0
            bucket = row["Topic"] if row["Topic"] in KNOWN_TOPICS else "OTHER"
            buckets[bucket].append(row)

    for key in buckets:
        buckets[key].sort(key=lambda r: r["_score"], reverse=True)

    selected: list[dict] = []
    seen_domains: set[str] = set()

    for topic, limit in ALLOCATIONS.items():
        count = 0
        for row in buckets.get(topic, []):
            if count >= limit:
                break
            if row["Domain"] not in seen_domains:
                seen_domains.add(row["Domain"])
                selected.append(row)
                count += 1

    return selected


# ---------------------------------------------------------------------------
# Prompt & parsing
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a media-literacy expert who evaluates whether news sources report "
    "factually accurate information. Be concise, balanced, and evidence-based."
)

USER_TEMPLATE = """\
Is {outlet_name} ({domain}, based in {country}) considered a reliable news source — \
meaning it consistently reports stories that are factually true?

Please respond in this exact format (no extra sections):

VERDICT: [Reliable / Unreliable / Mixed]

REASONING:
<2-4 sentences covering: factual accuracy track record, editorial standards, \
any known bias or misinformation incidents, and independent assessments \
(e.g. MBFC, Reuters Institute, press freedom indices). \
Explain your reasoning process briefly.>

CONFIDENCE: [1-5]  (1 = very uncertain, 5 = very confident)
"""


def query_gpt(outlet_name: str, domain: str, country: str) -> dict:
    prompt = USER_TEMPLATE.format(outlet_name=outlet_name, domain=domain, country=country)

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=400,
    )

    text = response.choices[0].message.content.strip()
    return parse_response(text)


def parse_response(text: str) -> dict:
    verdict = ""
    reasoning = ""
    confidence = ""

    lines = text.splitlines()
    in_reasoning = False
    reasoning_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped.upper().startswith("VERDICT:"):
            verdict = stripped.split(":", 1)[1].strip()
            in_reasoning = False
        elif stripped.upper().startswith("REASONING:"):
            in_reasoning = True
            after = stripped.split(":", 1)[1].strip()
            if after:
                reasoning_lines.append(after)
        elif stripped.upper().startswith("CONFIDENCE:"):
            in_reasoning = False
            raw = stripped.split(":", 1)[1].strip()
            # Extract just the number
            confidence = raw.split()[0].rstrip(".")
        elif in_reasoning and stripped:
            reasoning_lines.append(stripped)

    reasoning = " ".join(reasoning_lines).strip()
    return {"verdict": verdict, "reasoning": reasoning, "confidence": confidence, "raw": text}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

OUTPUT_FIELDS = [
    "Rank", "Domain", "Outlet Name", "MediaRank Score",
    "Country Code", "Country Name", "Topic",
    "Verdict", "Confidence (1-5)", "Reasoning",
]


def main():
    sources = select_sources()
    print(f"Selected {len(sources)} sources. Starting GPT evaluation...\n")

    OUTPUT_CSV.parent.mkdir(exist_ok=True)
    results = []

    for i, row in enumerate(sources, 1):
        outlet = row["Outlet Name"]
        domain = row["Domain"]
        country = row["Country Name"]
        print(f"[{i:3}/{len(sources)}] {outlet} ({domain}) — {country}")

        try:
            parsed = query_gpt(outlet, domain, country)
            results.append({
                "Rank": row["Rank"],
                "Domain": domain,
                "Outlet Name": outlet,
                "MediaRank Score": row["MediaRank Score"],
                "Country Code": row["Country Code"],
                "Country Name": country,
                "Topic": row["Topic"],
                "Verdict": parsed["verdict"],
                "Confidence (1-5)": parsed["confidence"],
                "Reasoning": parsed["reasoning"],
            })
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({
                "Rank": row["Rank"],
                "Domain": domain,
                "Outlet Name": outlet,
                "MediaRank Score": row["MediaRank Score"],
                "Country Code": row["Country Code"],
                "Country Name": country,
                "Topic": row["Topic"],
                "Verdict": "ERROR",
                "Confidence (1-5)": "",
                "Reasoning": str(e),
            })

        # Polite rate-limit pause
        time.sleep(1.0)

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(results)

    print(f"\nDone. Results saved to {OUTPUT_CSV}")

    # Quick summary
    verdicts = [r["Verdict"] for r in results if r["Verdict"] != "ERROR"]
    from collections import Counter
    print("\nVerdict summary:")
    for verdict, count in Counter(verdicts).most_common():
        print(f"  {verdict}: {count}")


if __name__ == "__main__":
    main()
