"""
ClearFrame pipeline orchestrator.

Stage implementations live in clearframe/stage*.py modules. This file keeps the
public run_clearframe_pipeline() entry point used by app.py and command-line runs.
"""

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import pandas as pd
from openai import OpenAI

from clearframe.config import (
    GDELT_OVERFETCH_FACTOR,
    GDELT_RESULTS_PER_COUNTRY,
    GATE_MODE,
    GDELT_FALLBACK_THRESHOLD,
    MAX_CANDIDATES_RANK,
    MAX_GDELT_RESULTS,
    STRUCTURAL_NOTE,
)
from clearframe.debug import dump_debug_run
from clearframe.display import print_dev_results, print_user_results
from clearframe.stage1_fetch import get_article_text
from clearframe.stage2_query_plan import (
    build_gdelt_query,
    clean_plan,
    make_query_plan,
    quote_if_needed,
)
from clearframe.stage3_gdelt_search import get_fallback_domain, search_gdelt_balanced, search_gdelt_fallback
from clearframe.stage5_topical_gate import topical_gate
from clearframe.stage6_fulltext import fetch_candidate_texts
from clearframe.prompts import CHOMSKY_CATEGORIES, COMPARATIVE_CATEGORIES, SINGLE_ARTICLE_CATEGORIES
from clearframe.stage7_chomsky import chomsky_pair_analysis, extract_source_article_analysis
from clearframe.stage8_selection import CATEGORY_PLAIN_LABELS
from clearframe.stage9_synthesis import synthesize_category_paragraphs

PAIR_ANALYSIS_MAX_WORKERS = 6


def run_clearframe_pipeline(
    source_url: str,
    api_key: str | None = None,
    max_gdelt_results: int = MAX_GDELT_RESULTS,
    gdelt_results_per_country: int = GDELT_RESULTS_PER_COUNTRY,
    gdelt_overfetch_factor: int = GDELT_OVERFETCH_FACTOR,
    max_candidates_rank: int = MAX_CANDIDATES_RANK,
    top_n: int | None = None,
    gate_mode: str = GATE_MODE
) -> dict:
    """
    Full ClearFrame pipeline, grounded in the Herman/Chomsky propaganda model.

    Provide a URL. The pipeline does the rest.

    Stages:
      1  trafilatura fetches the base article + publication date
      2  LLM builds a structured GDELT query plan, including article type
      3  GDELT returns candidate articles (+ regional fallback)
      4  Reuse the query plan's article type for topical relevance
      5/6  Topical gate + full-text fetch. Order depends on gate_mode:
             "metadata" â€” gate on title/metadata (5), then fetch text for survivors (6)
             "fulltext" â€” fetch text for all candidates (5), then gate on the body (6)
      7  Chomsky pair analysis: base <-> candidate, full text, per-category findings
      8  Category synthesis: meaningful differences only, no ranking
      9  Display and a timestamped debug dump

    Args:
        source_url          : URL of the article the user is reading
        api_key             : OpenAI API key (falls back to OPENAI_API_KEY env var)
        max_gdelt_results   : Deprecated; use gdelt_results_per_country instead
        gdelt_results_per_country: How many GDELT articles to request per query country
        gdelt_overfetch_factor: Combined GDELT request multiplier before per-country capping
        max_candidates_rank : Deprecated; all gathered GDELT articles now go to the topical gate
        top_n               : Deprecated; final output is category-based and unranked
        gate_mode           : "metadata" (gate on title, then fetch survivors) or
                              "fulltext" (fetch all candidates, then gate on the body).
                              Defaults to the CLEARFRAME_GATE_MODE env var.

    Returns:
        dict with all intermediate and final outputs for debugging
    """
    client = OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))

    gate_mode = (gate_mode or "metadata").strip().lower()
    if gate_mode not in ("metadata", "fulltext"):
        print(f"      [WARNING] Unknown gate_mode '{gate_mode}'; falling back to 'metadata'.")
        gate_mode = "metadata"

    def _early_exit(**extra) -> dict:
        base = {
            "source_url": source_url, "article_text": "", "plan": None, "query": None,
            "gdelt_df": pd.DataFrame(), "article_type": None, "gate_results": [],
            "fulltext_df": pd.DataFrame(), "pair_analyses": [],
            "selected_df": pd.DataFrame(),
            "synthesis": {"summary": "", "categories": {}, "structural_note": STRUCTURAL_NOTE},
        }
        base.update(extra)
        return base

    # â”€â”€ Stage 1: Fetch base article via trafilatura â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    print("\n[1/9] Fetching base article via trafilatura...")
    article_text, pub_date = get_article_text(source_url)
    if not article_text:
        raise ValueError(f"trafilatura could not extract text from: {source_url}")
    print(f"      Extracted {len(article_text)} characters.")
    print(f"      Preview: {article_text[:200]}...\n")

    # â”€â”€ Stage 2: Build GDELT query plan â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    print("[2/9] Building GDELT query plan...")
    plan               = make_query_plan(article_text, source_url, client)
    plan               = clean_plan(plan, max_terms=4)
    query, start_dt, end_dt = build_gdelt_query(
        plan["location"], plan["terms"], plan["query_countries"],
        pub_date, plan["window_days_before"], plan["window_days_after"]
    )
    event_country = plan["source_country"]
    article_type = plan["article_type"]
    print(f"      Plan     : {plan}")
    print(f"      Query    : {query}")
    print(f"      Date range: {start_dt} â†’ {end_dt}")
    print(f"      Event country (used to prefer local sources): {event_country}")
    print(f"      Original source country excluded: {plan['original_source_country']}")
    print(f"      Actor countries searched: {', '.join(plan['query_countries'])}")
    print(f"      Article type: {article_type}")

    # â”€â”€ Stage 3: Search GDELT â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    loc         = quote_if_needed(plan["location"])
    tparts      = " OR ".join(quote_if_needed(t) for t in plan["terms"])
    terms_query = f"{loc} AND ({tparts})"

    print(f"\n[3/9] Searching GDELT ({start_dt[:8]} to {end_dt[:8]}, "
          f"one combined request, cap={gdelt_results_per_country} per country)...")
    gdelt_articles = search_gdelt_balanced(
        query,
        plan["query_countries"],
        startdatetime=start_dt,
        enddatetime=end_dt,
        maxrecords_per_country=gdelt_results_per_country,
        overfetch_factor=gdelt_overfetch_factor,
    )
    gdelt_df = pd.DataFrame(gdelt_articles)
    print(f"      GDELT returned {len(gdelt_df)} articles.")

    # â”€â”€ Stage 3b: Regional fallback if too few results â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if len(gdelt_df) < GDELT_FALLBACK_THRESHOLD:
        fallback_domain = get_fallback_domain(plan["source_country"])
        print(f"      Only {len(gdelt_df)} result(s) â€” below threshold ({GDELT_FALLBACK_THRESHOLD}). "
              f"Triggering regional fallback.")
        print(f"      Fallback domain: {fallback_domain} "
              f"(mapped from country: '{plan['source_country']}')")

        fallback_results = search_gdelt_fallback(
            terms_query, fallback_domain, start_dt, end_dt, maxrecords=gdelt_results_per_country
        )
        fallback_df = pd.DataFrame(fallback_results.get("articles", []))

        if not fallback_df.empty:
            gdelt_df = (
                pd.concat([gdelt_df, fallback_df], ignore_index=True)
                .drop_duplicates(subset=["url"])
                .reset_index(drop=True)
            )
            print(f"      After fallback merge: {len(gdelt_df)} total article(s).")
        else:
            print(f"      [WARNING] Fallback search also returned 0 results. Continuing with what we have.")

    if gdelt_df.empty:
        print("      No results from GDELT. Exiting early.")
        return _early_exit(article_text=article_text, plan=plan, query=query)

    candidates_df = gdelt_df.reset_index(drop=True)
    print(f"      Passing all {len(candidates_df)} gathered GDELT article(s) to the topical gate.")

    # â”€â”€ Stage 4: Classify base article â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    print("\n[4/9] Reusing query-plan article type for topical relevance...")
    print(f"      Article type: {article_type}")

    common = {"article_text": article_text, "plan": plan, "query": query,
              "gdelt_df": gdelt_df, "article_type": article_type}

    def _print_gate(gate_results: list[dict]) -> int:
        n_pass = sum(1 for r in gate_results if r.get("topically_relevant"))
        for r in gate_results:
            verdict = "PASS" if r.get("topically_relevant") else "drop"
            domain  = str(candidates_df.iloc[r["row_index"]].get("domain", "?"))
            print(f"        [{verdict}] row {r['row_index']:<2} {domain:<28} {r.get('reason', '')}")
        print(f"      {n_pass}/{len(gate_results)} candidate(s) are about the same event.")
        return n_pass

    if gate_mode == "fulltext":
        # â”€â”€ Stage 5: Full-text fetch (all candidates) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        print(f"\n[5/9] Fetching full text for all {len(candidates_df)} candidate(s) "
              f"(gate_mode='fulltext', local sources first)...")
        prelim_df = fetch_candidate_texts(
            candidates_df, list(range(len(candidates_df))), event_country
        )
        if prelim_df.empty:
            print("      No candidate yielded usable full text. Exiting early.")
            return _early_exit(**common, gate_results=[])

        # â”€â”€ Stage 6: Topical gate on the fetched full text â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        texts = {int(r["row_index"]): str(r["article_text"])
                 for _, r in prelim_df.iterrows()}
        print(f"\n[6/9] Topical gate over {len(texts)} full-text candidate(s) "
              f"(binary same-event filter on the article body â€” no scoring)...")
        gate_results = topical_gate(article_text, candidates_df, article_type, client,
                                    texts=texts)
        n_pass = _print_gate(gate_results)

        if n_pass == 0:
            print("      Nothing passed the topical gate. Exiting early.")
            return _early_exit(**common, gate_results=gate_results)

        # Keep every survivor that already has text.
        passed = {r["row_index"] for r in gate_results if r.get("topically_relevant")}
        fulltext_df = (
            prelim_df[prelim_df["row_index"].isin(passed)]
            .reset_index(drop=True)
        )
        print(f"      {len(fulltext_df)} candidate(s) carried into pair analysis.")
    else:
        # â”€â”€ Stage 5: Topical gate on title/metadata â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        print(f"\n[5/9] Topical gate over {len(candidates_df)} candidates "
              f"(binary same-event filter â€” no scoring)...")
        gate_results = topical_gate(article_text, candidates_df, article_type, client)
        n_pass = _print_gate(gate_results)

        if n_pass == 0:
            print("      Nothing passed the topical gate. Exiting early.")
            return _early_exit(**common, gate_results=gate_results)

        # â”€â”€ Stage 6: Full-text fetch (survivors only) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        print("\n[6/9] Fetching full text for every topically relevant candidate "
              "(local sources first)...")
        passed = [r["row_index"] for r in gate_results if r.get("topically_relevant")]
        fulltext_df = fetch_candidate_texts(candidates_df, passed, event_country)

    if fulltext_df.empty:
        print("      No candidate yielded usable full text. Exiting early.")
        return _early_exit(**common, gate_results=gate_results)

    # â”€â”€ Stage 7: Chomsky pair analysis â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    print(f"\n[7/9] Chomsky pair analysis over {len(fulltext_df)} full-text candidate(s)...")
    print(f"      First extracting your article once across "
          f"{len(SINGLE_ARTICLE_CATEGORIES)} single-article categories.")
    source_analysis = extract_source_article_analysis(article_text, source_url, client)
    print("      Source extraction complete. Reusing that fixed source analysis for "
          f"{', '.join(SINGLE_ARTICLE_CATEGORIES)}.")
    print("      Comparative categories are analyzed directly between your article and "
          f"each GDELT article: {', '.join(COMPARATIVE_CATEGORIES)}.")

    pair_analyses:   list[dict]      = []

    rows = [row for _, row in fulltext_df.iterrows()]
    workers = min(PAIR_ANALYSIS_MAX_WORKERS, len(rows))
    print(f"      Running {len(rows)} one-candidate pair-analysis LLM call(s), "
          f"parallelism={workers}.")

    def analyze_one(row) -> tuple[str, dict]:
        domain = str(row.get("domain", "unknown"))
        try:
            analysis = chomsky_pair_analysis(article_text, source_analysis, row, client)
        except Exception as e:
            row_index = int(row.get("row_index", -1))
            print(f"      [WARNING] Pair analysis failed for row {row_index}: {e}")
            analysis = {
                "row_index": row_index,
                "article_reference": {
                    "title": str(row.get("title", "")),
                    "outlet": str(row.get("domain", "")),
                    "source_country": str(row.get("sourcecountry", "")),
                    "url": str(row.get("url", "")),
                },
                "category_answers": {
                    name: {
                        "source_article": source_analysis.get(name, {}) if name in SINGLE_ARTICLE_CATEGORIES else {},
                        "comparison_article": {},
                        "meaningful_difference": False,
                        "difference": "",
                        "source_basis": [],
                        "comparison_basis": [],
                    }
                    for name in CHOMSKY_CATEGORIES
                },
            }
        return domain, analysis

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(analyze_one, row) for row in rows]
        for future in as_completed(futures):
            domain, analysis = future.result()
            pair_analyses.append(analysis)

            answers = analysis.get("category_answers", {})
            populated = [
                name for name, answer in answers.items()
                if isinstance(answer, dict)
                and (
                    answer.get("meaningful_difference")
                    or (isinstance(answer.get("comparison_article"), dict)
                        and answer["comparison_article"].get("applies"))
                )
            ]
            print(f"\n      [done] {domain} (row {int(analysis.get('row_index', -1))})")
            if populated:
                print(f"           Extracted observations: {', '.join(populated)}")
            else:
                print("           Extracted observations: none.")

    pair_analyses.sort(key=lambda pa: int(pa.get("row_index", 0)))

    # Stage 8/9: Category synthesis and display. No article ranking or scoring.
    print(f"\n[8/9] Synthesising category paragraphs from {len(pair_analyses)} pair extraction(s)...")
    synthesis = synthesize_category_paragraphs(pair_analyses, article_text, client)
    print(f"      Produced {len(synthesis.get('categories', {}))} category paragraph(s) "
          "and one concise overall summary.")

    print("\n[9/9] Displaying category results and writing debug dump...")
    print_user_results(synthesis)
    print_dev_results(fulltext_df, pair_analyses)

    dump_path = dump_debug_run({
        "timestamp":       datetime.now(timezone.utc).isoformat(),
        "source_url":      source_url,
        "plan":            plan,
        "query":           query,
        "article_type":    article_type,
        "gate_results":    gate_results,
        "fetched_text_metadata": [
            {"row_index": int(r["row_index"]), "domain": str(r.get("domain", "")),
             "url": str(r.get("url", "")), "sourcecountry": str(r.get("sourcecountry", "")),
             "query_country": str(r.get("query_country", "")),
             "is_local": bool(r.get("is_local", False)),
             "text_length": len(str(r.get("article_text", "")))}
            for _, r in fulltext_df.iterrows()
        ],
        "source_analysis": source_analysis,
        "pair_analyses":   pair_analyses,
        "synthesis": synthesis,
    })
    if dump_path:
        print(f"\n  [DEV] Full run dumped to: {dump_path}")

    return {
        "source_url":      source_url,
        "article_text":    article_text,
        "plan":            plan,
        "query":           query,
        "gdelt_df":        gdelt_df,
        "article_type":    article_type,
        "gate_results":    gate_results,
        "fulltext_df":     fulltext_df,
        "source_analysis": source_analysis,
        "pair_analyses":   pair_analyses,
        "selected_df":     pd.DataFrame(),
        "synthesis":       synthesis,
    }


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# ENTRY POINT
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

if __name__ == "__main__":

    # Swap any of these in to test different article types
    # SOURCE_URL = "https://apnews.com/article/philippines-building-collapse-angeles-city-pampanga-clark-6a04bcd1f62ad8d625ab58a87512cd5c"
    # SOURCE_URL = "https://apnews.com/article/rwanda-genocide-suspect-kabuda-dies-hague-d9c0156deb1359429cb22ea8441974e9"
    # SOURCE_URL = "https://www.washingtonpost.com/world/2026/03/17/us-iran-israel-war-ali-larijani/"
    # SOURCE_URL = "https://www.aljazeera.com/news/2026/3/17/many-killed-wounded-after-blasts-hit-nigerias-maiduguri-witnesses-say"
    # SOURCE_URL = "https://www.who.int/news/item/09-01-2026-sudan-1000-days-of-war-deepen-the-world-s-worst-health-and-humanitarian-crisis"
    # SOURCE_URL = "https://www.nbcnews.com/world/north-korea/north-korea-fires-missiles-sea-show-force-seoul-rcna263450"
    # SOURCE_URL = "https://www.cbc.ca/news/world/venezuela-us-influence-trump-9.7122944"
    # SOURCE_URL = "https://www.nytimes.com/2026/03/14/business/media/washington-post-jeff-bezos-layoffs.html"
    # SOURCE_URL = "https://www.reuters.com/world/asia-pacific/hopes-dim-swift-end-iran-war-after-trump-speech-oil-prices-surge-anew-2026-04-02/"
    # SOURCE_URL = "https://apnews.com/article/iran-war-khamenei-politics-religion-society-a9e0405878db8266e1965d7c0b396243"
    SOURCE_URL = "https://apnews.com/article/ukraine-russia-war-kyiv-strikes-july-2026-83bcba8bb972ce248a805bc576a7322c"
    output = run_clearframe_pipeline(source_url=SOURCE_URL)


