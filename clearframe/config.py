import os

from dotenv import load_dotenv

load_dotenv()
MODEL_MINI   = "gpt-4o-mini"   # lightweight tasks: query plan and topical gate
MODEL_FULL   = "gpt-4o"        # heavier tasks: article extraction, pair analysis, synthesis

GDELT_URL    = "https://api.gdeltproject.org/api/v2/doc/doc"

GDELT_RESULTS_PER_COUNTRY = 10  # final diverse-article cap per country
GDELT_OVERFETCH_FACTOR = 3      # candidate-pool multiplier before diversity filtering
MAX_ARTICLES_PER_OUTLET = 2     # within-country outlet cap
NEAR_DUP_BODY_THRESHOLD = 0.70  # five-word-shingle Jaccard similarity
NEAR_DUP_TITLE_THRESHOLD = 0.85 # title-token Jaccard similarity

DEBUG_DUMP_DIR = "debug_runs"   # timestamped per-run JSON dumps, for prompt iteration

# Shown verbatim with every set of results. The propaganda model is structural;
# this line exists so no reader can take the findings as claims about intent.
STRUCTURAL_NOTE = (
    "These patterns reflect how news systems are structured â€” outlet position, "
    "audience, and sourcing â€” not the intent of individual journalists."
)

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# REGIONAL FALLBACK CONFIG
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

GDELT_FALLBACK_THRESHOLD = 5   # trigger fallback if GDELT returns fewer than this many results

COUNTRY_FALLBACK: dict[str, str] = {
    # Middle East and North Africa â†’ Al Jazeera
    "iraq":         "aljazeera.net",
    "syria":        "aljazeera.net",
    "iran":         "aljazeera.net",
    "yemen":        "aljazeera.net",
    "libya":        "aljazeera.net",
    "egypt":        "aljazeera.net",
    "saudi arabia": "aljazeera.net",
    "jordan":       "aljazeera.net",
    "lebanon":      "aljazeera.net",
    "palestine":    "aljazeera.net",
    "tunisia":      "aljazeera.net",
    "morocco":      "aljazeera.net",
    "algeria":      "aljazeera.net",
    "oman":         "aljazeera.net",
    # Africa â†’ AllAfrica
    "nigeria":      "allafrica.com",
    "ethiopia":     "allafrica.com",
    "kenya":        "allafrica.com",
    "ghana":        "allafrica.com",
    "sudan":        "allafrica.com",
    "somalia":      "allafrica.com",
    "drc":          "allafrica.com",
    "tanzania":     "allafrica.com",
    "uganda":       "allafrica.com",
    "mozambique":   "allafrica.com",
    "zimbabwe":     "allafrica.com",
    "cameroon":     "allafrica.com",
    "senegal":      "allafrica.com",
    "mali":         "allafrica.com",
    "burkina faso": "allafrica.com",
    # Central America â†’ El Faro
    "el salvador":  "elfaro.net",
    "guatemala":    "elfaro.net",
    "honduras":     "elfaro.net",
    "nicaragua":    "elfaro.net",
    "costa rica":   "elfaro.net",
    "panama":       "elfaro.net",
    "belize":       "elfaro.net",
    "mexico":       "elfaro.net",
    # South America â†’ AgÃªncia PÃºblica
    "colombia":     "apublica.org",
    "venezuela":    "apublica.org",
    "brazil":       "apublica.org",
    "argentina":    "apublica.org",
    "peru":         "apublica.org",
    "chile":        "apublica.org",
    "ecuador":      "apublica.org",
    "bolivia":      "apublica.org",
    "paraguay":     "apublica.org",
    "uruguay":      "apublica.org",
    "guyana":       "apublica.org",
    # Europe â†’ Euronews
    "ukraine":      "euronews.com",
    "russia":       "euronews.com",
    "poland":       "euronews.com",
    "hungary":      "euronews.com",
    "serbia":       "euronews.com",
    "turkey":       "euronews.com",
    "greece":       "euronews.com",
    "romania":      "euronews.com",
    "belarus":      "euronews.com",
    "georgia":      "euronews.com",
    "albania":      "euronews.com",
    "kosovo":       "euronews.com",
    "moldova":      "euronews.com",
    # Asia â†’ Channel News Asia
    "myanmar":      "channelnewsasia.com",
    "afghanistan":  "channelnewsasia.com",
    "pakistan":     "channelnewsasia.com",
    "bangladesh":   "channelnewsasia.com",
    "sri lanka":    "channelnewsasia.com",
    "thailand":     "channelnewsasia.com",
    "indonesia":    "channelnewsasia.com",
    "philippines":  "channelnewsasia.com",
    "north korea":  "channelnewsasia.com",
    "cambodia":     "channelnewsasia.com",
    "laos":         "channelnewsasia.com",
    "vietnam":      "channelnewsasia.com",
    "nepal":        "channelnewsasia.com",
}

FALLBACK_DEFAULT = "reuters.com"

