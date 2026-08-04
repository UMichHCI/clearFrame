"""
ClearFrame pipeline orchestrator.

Stage implementations live in clearframe/stage*.py modules. This file keeps the
public run_clearframe_pipeline() entry point used by app.py and command-line runs.
"""

import os
from datetime import datetime, timezone

import pandas as pd
from openai import OpenAI

from clearframe.config import (
    GATE_MODE,
    GDELT_FALLBACK_THRESHOLD,
    MAX_CANDIDATES_RANK,
    MAX_DISPLAY,
    MAX_FULLTEXT_CANDIDATES,
    MAX_GDELT_RESULTS,
    STRUCTURAL_NOTE,
)
from clearframe.debug import _df_records, dump_debug_run
from clearframe.display import print_dev_results, print_user_results
from clearframe.stage1_fetch import get_article_text
from clearframe.stage2_query_plan import (
    build_gdelt_query,
    clean_plan,
    make_query_plan,
    quote_if_needed,
)
from clearframe.stage3_gdelt_search import get_fallback_domain, search_gdelt, search_gdelt_fallback
from clearframe.stage4_classify import classify_article
from clearframe.stage5_topical_gate import topical_gate
from clearframe.stage6_fulltext import fetch_candidate_texts
from clearframe.stage7_chomsky import CHOMSKY_CATEGORIES, chomsky_pair_analysis, get_outlet_context
from clearframe.stage8_selection import CATEGORY_PLAIN_LABELS, score_illumination, select_by_illumination
from clearframe.stage9_synthesis import synthesize_brief


def run_clearframe_pipeline(
    source_url: str,
    api_key: str | None = None,
    max_gdelt_results: int = MAX_GDELT_RESULTS,
    max_candidates_rank: int = MAX_CANDIDATES_RANK,
    max_fulltext: int = MAX_FULLTEXT_CANDIDATES,
    top_n: int = MAX_DISPLAY,
    gate_mode: str = GATE_MODE
) -> dict:
    """
    Full ClearFrame pipeline, grounded in the Herman/Chomsky propaganda model.

    Provide a URL. The pipeline does the rest.

    Stages:
      1  trafilatura fetches the base article + publication date
      2  LLM builds a structured GDELT query plan
      3  GDELT returns candidate articles (+ regional fallback)
      4  LLM classifies the base article type
      5/6  Topical gate + full-text fetch. Order depends on gate_mode:
             "metadata" â€” gate on title/metadata (5), then fetch text for survivors (6)
             "fulltext" â€” fetch text for all candidates (5), then gate on the body (6)
      7  Chomsky pair analysis: base <-> candidate, full text, per-category findings
      8  Selection: deterministic illumination score, top N
      9  Synthesis, display, and a timestamped debug dump

    Args:
        source_url          : URL of the article the user is reading
        api_key             : OpenAI API key (falls back to OPENAI_API_KEY env var)
        max_gdelt_results   : How many articles to pull from GDELT (default 50)
        max_candidates_rank : Deprecated; all gathered GDELT articles now go to the topical gate
        max_fulltext        : How many gated candidates to fetch full text for (default 10)
        top_n               : How many to show to the user (default 5)
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
            "gdelt_df": pd.DataFrame(), "classification": None, "gate_results": [],
            "fulltext_df": pd.DataFrame(), "outlet_contexts": {}, "pair_analyses": [],
            "selected_df": pd.DataFrame(),
            "synthesis": {"overall_synthesis": "", "structural_note": STRUCTURAL_NOTE},
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
    print(f"      Plan     : {plan}")
    print(f"      Query    : {query}")
    print(f"      Date range: {start_dt} â†’ {end_dt}")
    print(f"      Event country (used to prefer local sources): {event_country}")
    print(f"      Original source country excluded: {plan['original_source_country']}")
    print(f"      Actor countries searched: {', '.join(plan['query_countries'])}")

    # â”€â”€ Stage 3: Search GDELT â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    print(f"\n[3/9] Searching GDELT ({start_dt[:8]} to {end_dt[:8]}, max={max_gdelt_results})...")
    gdelt_results = search_gdelt(query, startdatetime=start_dt, enddatetime=end_dt, maxrecords=max_gdelt_results)
    gdelt_df      = pd.DataFrame(gdelt_results.get("articles", []))
    print(f"      GDELT returned {len(gdelt_df)} articles.")

    # â”€â”€ Stage 3b: Regional fallback if too few results â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if len(gdelt_df) < GDELT_FALLBACK_THRESHOLD:
        fallback_domain = get_fallback_domain(plan["source_country"])
        print(f"      Only {len(gdelt_df)} result(s) â€” below threshold ({GDELT_FALLBACK_THRESHOLD}). "
              f"Triggering regional fallback.")
        print(f"      Fallback domain: {fallback_domain} "
              f"(mapped from country: '{plan['source_country']}')")

        # Build the terms-only portion of the query (strip sourcecountry clause)
        loc         = quote_if_needed(plan["location"])
        tparts      = " OR ".join(quote_if_needed(t) for t in plan["terms"])
        terms_query = f"{loc} AND ({tparts})"

        fallback_results = search_gdelt_fallback(
            terms_query, fallback_domain, start_dt, end_dt, maxrecords=max_gdelt_results
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
    print("\n[4/9] Classifying base article type...")
    classification = classify_article(article_text, client)
    print(f"      Primary type : {classification.get('primary_type')}")
    print(f"      Secondary    : {classification.get('secondary_type')}")
    print(f"      Justification: {classification.get('justification')}")

    common = {"article_text": article_text, "plan": plan, "query": query,
              "gdelt_df": gdelt_df, "classification": classification}

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
            candidates_df, list(range(len(candidates_df))), event_country,
            max_candidates=len(candidates_df)
        )
        if prelim_df.empty:
            print("      No candidate yielded usable full text. Exiting early.")
            return _early_exit(**common, gate_results=[])

        # â”€â”€ Stage 6: Topical gate on the fetched full text â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        texts = {int(r["row_index"]): str(r["article_text"])
                 for _, r in prelim_df.iterrows()}
        print(f"\n[6/9] Topical gate over {len(texts)} full-text candidate(s) "
              f"(binary same-event filter on the article body â€” no scoring)...")
        gate_results = topical_gate(article_text, candidates_df, classification, client,
                                    texts=texts)
        n_pass = _print_gate(gate_results)

        if n_pass == 0:
            print("      Nothing passed the topical gate. Exiting early.")
            return _early_exit(**common, gate_results=gate_results)

        # Keep only the survivors that already have text, capped for Stage 7.
        # prelim_df is already ordered local-first, so head() keeps locals.
        passed = {r["row_index"] for r in gate_results if r.get("topically_relevant")}
        fulltext_df = (
            prelim_df[prelim_df["row_index"].isin(passed)]
            .head(max_fulltext)
            .reset_index(drop=True)
        )
        print(f"      {len(fulltext_df)} candidate(s) carried into pair analysis "
              f"(cap {max_fulltext}).")
    else:
        # â”€â”€ Stage 5: Topical gate on title/metadata â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        print(f"\n[5/9] Topical gate over {len(candidates_df)} candidates "
              f"(binary same-event filter â€” no scoring)...")
        gate_results = topical_gate(article_text, candidates_df, classification, client)
        n_pass = _print_gate(gate_results)

        if n_pass == 0:
            print("      Nothing passed the topical gate. Exiting early.")
            return _early_exit(**common, gate_results=gate_results)

        # â”€â”€ Stage 6: Full-text fetch (survivors only) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        print(f"\n[6/9] Fetching full text (up to {max_fulltext}, local sources first)...")
        passed = [r["row_index"] for r in gate_results if r.get("topically_relevant")]
        fulltext_df = fetch_candidate_texts(candidates_df, passed, event_country,
                                            max_candidates=max_fulltext)

    if fulltext_df.empty:
        print("      No candidate yielded usable full text. Exiting early.")
        return _early_exit(**common, gate_results=gate_results)

    # â”€â”€ Stage 7: Chomsky pair analysis â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    print(f"\n[7/9] Chomsky pair analysis over {len(fulltext_df)} full-text candidate(s)...")
    print(f"      Each pair is analysed against the base article across "
          f"{len(CHOMSKY_CATEGORIES)} categories.")
    print("      'applies: false' is expected â€” most pairs evidence only 1-3 categories.")

    outlet_contexts: dict[str, dict] = {}
    pair_analyses:   list[dict]      = []

    for n, (_, row) in enumerate(fulltext_df.iterrows(), start=1):
        domain = str(row.get("domain", "unknown"))
        print(f"\n      [{n}/{len(fulltext_df)}] {domain} (row {int(row['row_index'])})")

        ctx = get_outlet_context(domain, client)
        outlet_contexts[domain] = ctx
        print(f"           [BACKEND ONLY] outlet context â€” state relationship: "
              f"{ctx.get('state_relationship')} (confidence: {ctx.get('confidence')})")

        analysis = chomsky_pair_analysis(article_text, row, ctx, client)
        pair_analyses.append(analysis)

        applying = [n_ for n_, c in analysis.get("categories", {}).items() if c.get("applies")]
        score, _ = score_illumination(analysis.get("categories", {}))
        if applying:
            print(f"           Applies: {', '.join(applying)}")
        else:
            print("           Applies: none â€” no evidenced finding for this pair.")
        print(f"           Illumination score: {score}")

    # â”€â”€ Stage 8: Selection by illumination score â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    print(f"\n[8/9] Selecting top {top_n} by illumination score "
          f"(computed in Python, deterministic)...")
    selected_df = select_by_illumination(fulltext_df, pair_analyses, event_country,
                                         max_count=top_n)

    if selected_df.empty:
        print("      No pair produced an evidenced finding. Nothing to surface.")
        return _early_exit(**common, gate_results=gate_results,
                           fulltext_df=fulltext_df, outlet_contexts=outlet_contexts,
                           pair_analyses=pair_analyses)

    for i, (_, row) in enumerate(selected_df.iterrows(), start=1):
        print(f"        #{i}  {row['illumination_score']:<6} {row.get('domain', '?'):<28} "
              f"strongest: {row.get('strongest_category', 'â€”')}")

    # â”€â”€ Stage 9: Synthesis and display â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    print(f"\n[9/9] Synthesising across the {len(selected_df)} selected pair(s)...")
    selected_rows      = set(int(r) for r in selected_df["row_index"])
    selected_for_synth = [
        {
            "outlet":           str(row.get("domain", "")),
            "source_country":   str(row.get("sourcecountry", "")),
            "title":            str(row.get("title", "")),
            "categories":       row.get("chomsky_findings", {}),
            "why_this_article": row.get("why_this_article", ""),
        }
        for _, row in selected_df.iterrows()
    ]
    synthesis = synthesize_brief(selected_for_synth, article_text, client)
    print("      Synthesis complete.")

    print_user_results(selected_df, synthesis)
    print_dev_results(fulltext_df, pair_analyses, outlet_contexts, selected_rows)

    dump_path = dump_debug_run({
        "timestamp":       datetime.now(timezone.utc).isoformat(),
        "source_url":      source_url,
        "plan":            plan,
        "query":           query,
        "classification":  classification,
        "gate_results":    gate_results,
        "fetched_text_metadata": [
            {"row_index": int(r["row_index"]), "domain": str(r.get("domain", "")),
             "url": str(r.get("url", "")), "sourcecountry": str(r.get("sourcecountry", "")),
             "is_local": bool(r.get("is_local", False)),
             "text_length": len(str(r.get("article_text", "")))}
            for _, r in fulltext_df.iterrows()
        ],
        "outlet_contexts": outlet_contexts,
        "pair_analyses":   pair_analyses,
        "scores": [
            {"row_index": int(pa["row_index"]),
             "illumination_score": score_illumination(pa.get("categories", {}))[0],
             "breakdown":          score_illumination(pa.get("categories", {}))[1]}
            for pa in pair_analyses
        ],
        "selected":  _df_records(selected_df, drop=("article_text",)),
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
        "classification":  classification,
        "gate_results":    gate_results,
        "fulltext_df":     fulltext_df,
        "outlet_contexts": outlet_contexts,
        "pair_analyses":   pair_analyses,
        "selected_df":     selected_df,
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

