# ClearFrame

**ClearFrame** takes a news article URL, finds other articles covering the same
event, and compares them through the analytic categories of Herman & Chomsky's
propaganda model (*Manufacturing Consent*, 1988) to surface what reading them
**together** reveals that no single article shows on its own.

There are two ways to run it:

- **Command line** â€” `run.py`, prints a full 9-stage log to your terminal.
- **Web UI** â€” `app.py`, a local page where you paste a URL and watch the same
  output stream live, plus a clean "Results" view. Built for debugging and
  validation.

---

## How it works

The pipeline runs in nine stages:

1. **Fetch** the base article text, headline, and publication date (`trafilatura`).
2. **Query plan** â€” an LLM identifies the article type and builds a structured GDELT search (location, countries, terms, time window).
3. **Search GDELT** for an overfetched candidate pool, with a regional fallback when needed.
4. **Full-text fetch** for every metadata-unique candidate, local sources first.
5. **NLP deduplication** clusters near-duplicate full texts within each country and keeps the most complete copy.
6. **Full-text topical gate** makes one binary "same event?" judgment per remaining article.
7. **Diversity selection** keeps up to 10 articles per country, no more than two per outlet, preferring different outlets first.
8. **Pair analysis** compares every selected article with the source across six propaganda-model categories.
9. **Synthesis + display** combines evidence-backed differences, displays them, and saves a debug record.

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

- **Console tab** â€” the full 9-stage terminal log streams in live as it runs
  (~30â€“90s). Good for debugging.
- **Results tab** â€” the selected comparison articles and the synthesis, rendered
  as clean cards. Good for validation and for non-technical readers. After each
  successful run, the same content is written to `results.json`, replacing the
  previous run's file. Use **Copy for Google Docs** to copy the complete result
  with headings, paragraphs, and linked references preserved.

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
|-- run.py                  # pipeline orchestrator / public entry point
|-- app.py                  # local web backend: serves the UI + streams the pipeline
|-- clearframe/             # pipeline implementation modules
|   |-- config.py           # shared constants and environment defaults
|   |-- llm.py              # shared OpenAI call helpers
|   |-- stage1_fetch.py     # base article fetch
|   |-- stage2_query_plan.py
|   |-- stage3_gdelt_search.py
|   |-- diversity.py        # metadata/text deduplication and outlet balancing
|   |-- stage5_topical_gate.py
|   |-- stage6_fulltext.py
|   |-- stage7_chomsky.py
|   |-- stage9_synthesis.py
|   |-- display.py
|   `-- debug.py
|-- static/                 # the web front end
|   |-- index.html          # markup
|   |-- style.css           # styles
|   `-- app.js              # client logic
|-- requirements.txt        # Python dependencies
|-- .env.example            # template for your API key
`-- debug_runs/             # per-run JSON dumps (gitignored)
```

The web front end (`app.py` + `static/`) uses **only the Python standard
library** â€” the dependencies in `requirements.txt` are for the pipeline itself.

---

## Troubleshooting

- **`Address already in use` when starting `app.py`** â€” a copy is already
  running. Either just open <http://localhost:8000>, or free the port:
  `lsof -ti :8000 | xargs kill -9` (macOS/Linux).
- **GDELT `429` / timeouts** â€” GDELT rate-limits by IP. The pipeline retries a
  few times automatically; if it persists, wait a minute and try again.
- **`trafilatura could not extract text`** â€” some sites block scrapers or use
  heavy JavaScript. Try a different article URL.

---

## Background

- Herman & Chomsky, *Manufacturing Consent* (1988)
- [GDELT 2.0](https://blog.gdeltproject.org/gdelt-2-0-our-global-world-in-realtime/)
- [trafilatura](https://trafilatura.readthedocs.io/)
