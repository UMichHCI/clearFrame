import pandas as pd

from .config import MAX_DISPLAY
from .stage2_query_plan import normalize_country
CONFIDENCE_WEIGHTS = {"high": 2.0, "medium": 1.0, "low": 0.25}

CATEGORY_WEIGHTS = {
    "worthy_unworthy_victims":  1.5,
    "suppressed_alternative":   1.5,
    "agency_attribution":       1.25,
    "presuppositions_doctrine": 1.0,
    "selective_criteria":       1.0,
    "smoke_and_discrepancies":  1.0,
}

# Plain-language lens names. The user never sees a raw category key.
CATEGORY_PLAIN_LABELS = {
    "worthy_unworthy_victims":  "different treatment of victims",
    "agency_attribution":       "who did it vs. what happened",
    "presuppositions_doctrine": "different assumptions",
    "selective_criteria":       "different standards applied",
    "suppressed_alternative":   "an account the original leaves out",
    "smoke_and_discrepancies":  "smoke / factual disagreement",
}


def score_illumination(categories: dict) -> tuple[float, list[dict]]:
    """
    Deterministic illumination score, plus a per-category breakdown for debugging.

    The 0.25 weight on low confidence is deliberate: stacking weak findings is nearly
    worthless, which reinforces the anti-over-finding guard at the scoring level rather
    than leaving it to the prompt alone.
    """
    breakdown: list[dict] = []
    total = 0.0

    for name, cat in categories.items():
        if not isinstance(cat, dict) or not cat.get("applies"):
            continue
        cat_w  = CATEGORY_WEIGHTS.get(name, 1.0)
        conf   = str(cat.get("confidence", "low")).lower()
        conf_w = CONFIDENCE_WEIGHTS.get(conf, CONFIDENCE_WEIGHTS["low"])
        points = conf_w * cat_w
        total += points
        breakdown.append({
            "category":    name,
            "confidence":  conf,
            "conf_weight": conf_w,
            "cat_weight":  cat_w,
            "points":      round(points, 3),
        })

    breakdown.sort(key=lambda b: b["points"], reverse=True)
    return round(total, 3), breakdown


def strongest_category(categories: dict) -> str:
    """The highest-weighted applying category, ties broken by confidence."""
    applying = [
        (name, cat) for name, cat in categories.items()
        if isinstance(cat, dict) and cat.get("applies")
    ]
    if not applying:
        return ""
    return max(
        applying,
        key=lambda kv: (
            CATEGORY_WEIGHTS.get(kv[0], 1.0),
            CONFIDENCE_WEIGHTS.get(str(kv[1].get("confidence", "low")).lower(), 0.25),
        ),
    )[0]


def select_by_illumination(candidates_df: pd.DataFrame, pair_analyses: list[dict],
                           event_country: str, max_count: int = MAX_DISPLAY) -> pd.DataFrame:
    """
    Ranks analysed pairs by their deterministic illumination score and takes the top
    max_count. Tiebreaker: a candidate whose sourcecountry matches the event country.

    candidates_df is the full-text DataFrame from Stage 6 (it carries `row_index`).
    """
    if candidates_df.empty or not pair_analyses:
        return pd.DataFrame()

    by_row = {int(row["row_index"]): row for _, row in candidates_df.iterrows()}
    event_ctry = normalize_country(event_country)

    ranked: list[dict] = []
    for pa in pair_analyses:
        idx = int(pa.get("row_index", -1))
        if idx not in by_row:
            continue
        row = by_row[idx]
        categories       = pa.get("categories", {})
        score, breakdown = score_illumination(categories)
        is_local = normalize_country(str(row.get("sourcecountry", ""))) == event_ctry
        ranked.append({
            "row_index":         idx,
            "row":               row,
            "illumination":      score,
            "breakdown":         breakdown,
            "categories":        categories,
            "why_this_article":  pa.get("why_this_article", ""),
            "is_local":          is_local,
        })

    if not ranked:
        return pd.DataFrame()

    ranked.sort(key=lambda r: (r["illumination"], 1 if r["is_local"] else 0), reverse=True)
    top = [r for r in ranked if r["illumination"] > 0][:max_count]

    # If nothing scored above zero, no pair produced an evidenced finding. Showing
    # the highest-ranked zero-score articles would be presenting an empty result as
    # a finding, so we surface nothing instead.
    if not top:
        return pd.DataFrame()

    out = pd.DataFrame([r["row"] for r in top]).reset_index(drop=True)
    out["illumination_score"] = [r["illumination"] for r in top]
    out["why_this_article"]   = [r["why_this_article"] for r in top]
    out["chomsky_findings"]   = [r["categories"] for r in top]
    out["strongest_category"] = [strongest_category(r["categories"]) for r in top]
    out["score_breakdown"]    = [r["breakdown"] for r in top]
    return out

