import os

from dotenv import load_dotenv

load_dotenv()
MODEL_MINI   = "gpt-6-luna"     # lightweight tasks: query plan and topical gate
MODEL_FULL   = "gpt-6.1-sol"    # heavier tasks: article extraction, pair analysis, synthesis
MODEL_MEMES  = os.environ.get("MEME_MODEL", MODEL_FULL)  # template selection and captions
MODEL_PERSPECTIVES = os.environ.get("PERSPECTIVE_MODEL", MODEL_FULL)

# Additional completion capacity for internal reasoning, beyond each stage's
# answer budget. These are ceilings, not fixed token usage or charges.
MODEL_REASONING = {
    MODEL_MINI: ("low", 4096),
    MODEL_FULL: ("medium", 25000),
}

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
    "News coverage can be shaped by an outlet's position, its audience, and the sources "
    "it relies on. These comparisons do not tell us what individual journalists intended."
)
