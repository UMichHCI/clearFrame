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
2. **Query plan** â€” an LLM identifies the article type and builds a structured GDELT search using event-specific terms, publishing countries, and an estimated coverage period. Location is descriptive metadata, not a required search phrase.
3. **Search GDELT** for an overfetched candidate pool from actor countries. Stop if the search fails or returns no candidates.
4. **Full-text fetch** for every metadata-unique candidate, local sources first.
5. **NLP deduplication** clusters near-duplicate full texts within each country and keeps the most complete copy.
6. **Full-text topical gate** makes one binary "same event?" judgment per remaining article.
7. **Diversity selection** keeps up to 10 articles per country, no more than two per outlet, preferring different outlets first.
8. **Pair analysis** compares every selected article with the source across six propaganda-model categories.
9. **Synthesis + display** combines evidence-backed differences, displays them, and saves a debug record.

Query planning and topical filtering use `gpt-6-luna` with low reasoning effort.
Article extraction, pair analysis, and synthesis use `gpt-6.1-sol` with medium
reasoning effort. Models and reasoning settings are configured in
`clearframe/config.py`. Completion limits include room for internal reasoning;
reasoning tokens contribute to API costs.

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
click **Compare articles**.

- **Results** — the main reading view, with the source headline, comparison
  counts, overall summary, numbered findings, supporting sources, and articles
  grouped by country. Use **Open saved results** to choose `results.json` or a
  saved run from `debug_runs/`. The file is read on your device and fills only
  Results; Progress and Details keep their current contents. No API key or
  server storage is needed to open a file. Reloading the page clears the import.
  The sidebar starts a new comparison without leaving the website. Results update
  automatically when a run completes. Both <http://localhost:8000> and
  <http://localhost:8000/results> open the same integrated workspace.
  The overall summary and each difference have independent **High fidelity** and
  **Low fidelity** tabs. High fidelity shows the full explanation and references;
  low fidelity shows that section's meme and one short sentence. You can mix the
  two views across sections. Switching tabs makes no model calls.
  The summary's **Comic** tab, immediately after **Middle fidelity**, displays
  the saved six-page Hormuz stick-figure comic as an example. It includes page
  navigation, full-size images, and expandable transcripts. Its images load only
  when the Comic tab is opened; it makes no model calls and does not generate a
  different comic for each comparison.
  The overall summary also has a **Middle fidelity** tab: an interactive map of
  coverage grouped by source country. Each country represented in the articles,
  including the original article's country, gets a marker. It summarizes that
  country's answer to one focused shared question, based on its sampled coverage,
  and notes differences between its outlets when relevant. The country names and
  marker count come from the article metadata. Comparisons appear on lines connecting
  countries in the world map: solid green lines indicate similar answers and dashed
  brown lines indicate different answers. Hover or keyboard-focus a line to see
  the country pair, comparison title, and explanation; click or tap to keep it open
  with sources. **Browse country comparisons** offers the same comparisons without
  needing to target a line. The world map is the only section in this view.
  Each country uses a complete, plain-language answer in first person (we/our)
  from the country's underlying worldview represented in the analysis as its bold
  headline. It voices the position itself rather than speaking as a reporter.
  Supporting explanations retain neutral source attribution and distinguish
  explicit positions from interpretation. The explanation and sources stay hidden
  until selected. Select a country to open its answer and highlight its map
  connections; select it again or use Close answer to dismiss it.
  **Answers around the world** places the answers on
  a locally bundled world map. Hover or keyboard-focus a marker to preview its
  answer; click or tap to keep its explanation and sources open. Nearby markers
  spread apart with lines back to their geographic locations. Drag to pan and
  use the zoom, World, or Fit countries controls. Country buttons provide an
  alternative to selecting markers, including when a location is unavailable.
  The map uses [Natural Earth](https://www.naturalearthdata.com/) geography and
  makes no additional model calls or external map-service requests.
  New comparisons request this map in its own single model call, independently
  of the meme request. Uploaded results without a map offer **Generate map**;
  opening a file or switching views does not generate one automatically.
  **Save results** includes the map so it can be reopened without another call.
  **Regenerate map** requests a replacement using your OpenAI account.
  `PERSPECTIVE_MODEL` optionally overrides the map model; it defaults to the
  configured full analysis model. No extra review, validation, or retry stage is
  used for map generation.
  New web
  comparisons generate captions in the background after the
  full results appear. The model receives analysis text and descriptions of the
  nine bundled templates; the browser draws captions over the local images.
  A single model request writes the memes and checks their fit and clarity before
  returning one final card per summary. Fictional examples from
  unrelated topics teach dialogue and joke structure. New explanatory sentences
  use at most 20 words. Expanded templates support speaker labels, longer
  conversational captions, and a tailored conclusion for the Pam template.
  Uploaded files without memes offer **Generate memes**, using the key in the
  sidebar. Opening a file stays local; making memes sends its summary text and
  supporting references to OpenAI and bills your account.
  **Save results** downloads a JSON file with any generated captions included.
  Reopening that file restores the saved views without another model call. Click a
  meme to show that section's high fidelity explanation. Failed meme generation can be retried and
  leaves the full report available. **Regenerate memes** makes a fresh set for
  existing results using your OpenAI account; older saved cards still open.
  `MEME_MODEL` optionally overrides the meme
  model; by default it uses the configured full analysis model.
  Use **Copy full text** to copy all full explanations with linked references for
  Google Docs, or **Print / PDF** to print the versions currently selected for
  each section without the app controls.
- **Progress** — the full 9-stage activity log streams live during a comparison.
- **Details** — inspect extractions and synthesis for runs completed in the
  current browser session.

After each successful web run, the results are written to `results.json`,
replacing the previous comparison. Each completed run also regenerates
`results-preview.html`, a standalone reading copy that opens directly in a
browser. Command-line runs regenerate the same HTML export.

Press **Ctrl+C** in the terminal to stop the server.

> **Note:** the UI runs the real pipeline, so each run makes live OpenAI API
> calls. Meme generation makes one model request, with no automatic correction,
> network, or rate-limit retries. Invalid output stops generation and
> leaves the full report available. Reading saved memes makes no model calls.
> Only one comparison pipeline runs at a time.

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
