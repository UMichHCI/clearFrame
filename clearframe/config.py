import os

from dotenv import load_dotenv

load_dotenv()
MODEL_MINI   = "gpt-4o-mini"   # lightweight tasks: query plan, classification, topical gate
MODEL_FULL   = "gpt-4o"        # heavier tasks: outlet context, pair analysis, synthesis

GDELT_URL    = "https://api.gdeltproject.org/api/v2/doc/doc"

MAX_GDELT_RESULTS       = 50    # max articles fetched from GDELT
MAX_CANDIDATES_RANK     = 20    # deprecated: all gathered GDELT candidates now go to the topical gate
MAX_FULLTEXT_CANDIDATES = 10    # max gated candidates we fetch full text for
MAX_DISPLAY             = 5     # max articles shown to user

# How the topical gate decides same-event relevance:
#   "metadata" â€” gate on title/domain/date only, then fetch full text for the
#                survivors. Cheap; the default.
#   "fulltext" â€” fetch full text for every candidate first, then gate on the
#                article body. More accurate but many more fetches (higher cost
#                and rate-limit exposure). Set CLEARFRAME_GATE_MODE in .env to flip.
GATE_MODE = os.environ.get("CLEARFRAME_GATE_MODE", "metadata").strip().lower()

DEBUG_DUMP_DIR = "debug_runs"   # timestamped per-run JSON dumps, for prompt iteration

# Shown verbatim with every set of results. The propaganda model is structural;
# this line exists so no reader can take the findings as claims about intent.
STRUCTURAL_NOTE = (
    "These patterns reflect how news systems are structured â€” outlet position, "
    "audience, and sourcing â€” not the intent of individual journalists."
)

_gdelt_request_count = 0     # debug counter â€” tracks GDELT API calls this run

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

