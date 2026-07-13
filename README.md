# ClearFrame

**ClearFrame** takes a news article URL, finds other articles covering the same
event, and compares them through the analytic categories of Herman & Chomsky's
propaganda model (*Manufacturing Consent*, 1988) to surface what reading them
**together** reveals that no single article shows on its own.

There are two ways to run it:

- **Command line** — `run.py`, prints a full 9-stage log to your terminal.
- **Web UI** — `app.py`, a local page where you paste a URL and watch the same
  output stream live, plus a clean "Results" view. Built for debugging and
  validation.

---

## How it works

The pipeline runs in nine stages:

1. **Fetch** the base article text + publication date (`trafilatura`).
2. **Query plan** — an LLM builds a structured GDELT search (location, country, terms, time window).
3. **Search GDELT** for candidate articles covering the same event (with a regional fallback).
4. **Classify** the base article's type (breaking news, ongoing situation, policy, historical, human-interest).
5. **Topical gate** — a lightweight binary "same event?" filter on titles/metadata.
6. **Full-text fetch** for the candidates that passed, local sources first.
7. **Pair analysis** — each candidate is compared against the base article across six propaganda-model categories, with verbatim-quote evidence required.
8. **Selection** — a deterministic illumination score (computed in Python) ranks the pairs; top 5 are kept.
9. **Synthesis + display** — a short reader-facing summary, plus a verbose developer view.

---

## Setup

You need **Python 3.11+** and an **OpenAI API key**.

```bash
# 1. Clone the repo
git clone https://github.com/aayyob/clearFrame.git
cd clearFrame

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Add your OpenAI API key
cp .env.example .env
#    then open .env and paste your key after OPENAI_API_KEY=
```

Get an API key at <https://platform.openai.com/api-keys>. Your `.env` file is
gitignored, so your key is never committed.

---

## Running the web UI (recommended)

```bash
python app.py
```

Then open **<http://localhost:8000>** in your browser, paste an article URL, and
click **Run pipeline**.

- **Console tab** — the full 9-stage terminal log streams in live as it runs
  (~30–90s). Good for debugging.
- **Results tab** — the selected comparison articles and the synthesis, rendered
  as clean cards. Good for validation and for non-technical readers.

Press **Ctrl+C** in the terminal to stop the server.

> **Note:** the UI runs the real pipeline, so each run makes live OpenAI API
> calls (same cost as a command-line run). Only one run happens at a time.

---

## Running from the command line

Edit the `SOURCE_URL` at the bottom of `run.py`, then:

```bash
python run.py
```

This prints the full pipeline log, the user-facing results, and a verbose
`[DEV]` section. Each run is also dumped to `debug_runs/<timestamp>.json` for
comparing prompt iterations.

---

## Project layout

```
clearFrame/
├── run.py              # the pipeline (all 9 stages)
├── app.py              # local web backend: serves the UI + streams the pipeline
├── static/             # the web front end
│   ├── index.html      #   markup
│   ├── style.css       #   styles
│   └── app.js          #   client logic
├── requirements.txt    # Python dependencies
├── .env.example        # template for your API key
└── debug_runs/         # per-run JSON dumps (gitignored)
```

The web front end (`app.py` + `static/`) uses **only the Python standard
library** — the dependencies in `requirements.txt` are for the pipeline itself.

---

## Troubleshooting

- **`Address already in use` when starting `app.py`** — a copy is already
  running. Either just open <http://localhost:8000>, or free the port:
  `lsof -ti :8000 | xargs kill -9` (macOS/Linux).
- **GDELT `429` / timeouts** — GDELT rate-limits by IP. The pipeline retries a
  few times automatically; if it persists, wait a minute and try again.
- **`trafilatura could not extract text`** — some sites block scrapers or use
  heavy JavaScript. Try a different article URL.

---

## Background

- Herman & Chomsky, *Manufacturing Consent* (1988)
- [GDELT 2.0](https://blog.gdeltproject.org/gdelt-2-0-our-global-world-in-realtime/)
- [trafilatura](https://trafilatura.readthedocs.io/)
