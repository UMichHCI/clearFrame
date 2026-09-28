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
    GDELT_FALLBACK_THRESHOLD,
    MAX_ARTICLES_PER_OUTLET,
    NEAR_DUP_BODY_THRESHOLD,
    NEAR_DUP_TITLE_THRESHOLD,
    STRUCTURAL_NOTE,
)
from clearframe.diversity import (
    deduplicate_candidate_metadata,
    remove_near_duplicate_texts,
    select_diverse_articles,
)
from clearframe.debug import dump_debug_run
from clearframe.display import print_dev_results, print_user_results
from clearframe.stage1_fetch import get_article_text
from clearframe.stage2_query_plan import (
    build_gdelt_query,
    clean_plan,
    find_non_country_actors,
    make_query_plan,
    quote_if_needed,
)
from clearframe.stage3_gdelt_search import (
    GDELTSearchError,
    get_fallback_domain,
    search_gdelt_balanced,
    search_gdelt_fallback,
)
from clearframe.stage5_topical_gate import topical_gate
from clearframe.stage6_fulltext import fetch_candidate_texts
from clearframe.prompts import (
    CATEGORY_PLAIN_LABELS,
    CHOMSKY_CATEGORIES,
    COMPARATIVE_CATEGORIES,
    SINGLE_ARTICLE_CATEGORIES,
)
from clearframe.stage7_chomsky import chomsky_pair_analysis, extract_source_article_analysis
from clearframe.stage9_synthesis import synthesize_category_paragraphs

PAIR_ANALYSIS_MAX_WORKERS = 6


def run_clearframe_pipeline(
    source_url: str,
    api_key: str | None = None,
    gdelt_results_per_country: int = GDELT_RESULTS_PER_COUNTRY,
    gdelt_overfetch_factor: int = GDELT_OVERFETCH_FACTOR,
    max_articles_per_outlet: int = MAX_ARTICLES_PER_OUTLET,
) -> dict:
    """
    Full ClearFrame pipeline, grounded in the Herman/Chomsky propaganda model.

    Provide a URL. The pipeline does the rest.

    Stages:
      1  trafilatura fetches the base article + publication date
      2  LLM builds a structured GDELT query plan, including article type
      3  GDELT returns an overfetched candidate pool (+ regional fallback)
      4  Fetch full text for the metadata-deduplicated pool
      5  Remove near-duplicate full texts with word-shingle similarity
      6  Full-text topical gate
      7  Select up to 10 articles per country with at most 2 per outlet
      8  Chomsky pair analysis over every selected article
      9  Category synthesis, display, and debug dump

    Args:
        source_url          : URL of the article the user is reading
        api_key             : OpenAI API key (falls back to OPENAI_API_KEY env var)
        gdelt_results_per_country: Final diverse-article cap per country
        gdelt_overfetch_factor: Candidate-pool multiplier before filtering
        max_articles_per_outlet: Final within-country cap for one outlet

    Returns:
        dict with all intermediate and final outputs for debugging
    """
    client = OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))

    def _early_exit(**extra) -> dict:
        base = {
            "source_url": source_url, "source_title": "", "article_text": "", "plan": None, "query": None,
            "gdelt_df": pd.DataFrame(), "article_type": None, "gate_results": [],
            "fulltext_df": pd.DataFrame(), "diverse_df": pd.DataFrame(),
            "pair_analyses": [],
            "stop_reason": "",
            "synthesis": {"summary": "", "categories": {}, "structural_note": STRUCTURAL_NOTE},
        }
        base.update(extra)
        return base

    # â”€â”€ Stage 1: Fetch base article via trafilatura â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    print("\n[1/9] Fetching base article via trafilatura...")
    article_text, pub_date, source_title = get_article_text(source_url)
    if not article_text:
        raise ValueError(f"trafilatura could not extract text from: {source_url}")
    print(f"      Extracted {len(article_text)} characters.")
    print(f"      Title: {source_title or '(not found)'}")
    print(f"      Preview: {article_text[:200]}...\n")

    # â”€â”€ Stage 2: Build GDELT query plan â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    print("[2/9] Building GDELT query plan...")
    plan               = make_query_plan(article_text, source_url, client)
    plan               = clean_plan(plan, max_terms=4)
    article_type = plan["article_type"]
    print(f"      Plan     : {plan}")
    print(f"      Article type: {article_type}")

    non_country_actors = find_non_country_actors(plan["actor_countries"])
    if non_country_actors:
        invalid_names = ", ".join(non_country_actors)
        stop_reason = (
            "The query plan identified an actor that is not a valid GDELT source "
            f"country: {invalid_names}. ClearFrame stopped before searching GDELT."
        )
        print(f"      [STOP] {stop_reason}")
        return _early_exit(
            source_title=source_title,
            article_text=article_text,
            plan=plan,
            article_type=article_type,
            stop_reason=stop_reason,
        )

    if len(plan["actor_countries"]) < 2:
        stop_reason = (
            "ClearFrame requires at least two distinct actor countries for comparative "
            "coverage, but the query plan identified only one: "
            f"{plan['actor_countries'][0]}."
        )
        print(f"      [STOP] {stop_reason}")
        return _early_exit(
            source_title=source_title,
            article_text=article_text,
            plan=plan,
            article_type=article_type,
            stop_reason=stop_reason,
        )

    query, start_dt, end_dt = build_gdelt_query(
        plan["location"], plan["terms"], plan["query_countries"],
        pub_date, plan["window_days_before"], plan["window_days_after"]
    )
    event_country = plan["source_country"]
    print(f"      Query    : {query}")
    print(f"      Date range: {start_dt} â†’ {end_dt}")
    print(f"      Event country (used to prefer local sources): {event_country}")
    print(f"      Original source country excluded: {plan['original_source_country']}")
    print(f"      Actor countries searched: {', '.join(plan['query_countries'])}")

    # â”€â”€ Stage 3: Search GDELT â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    loc         = quote_if_needed(plan["location"])
    tparts      = " OR ".join(quote_if_needed(t) for t in plan["terms"])
    terms_query = f"{loc} AND ({tparts})"

    print(f"\n[3/9] Searching GDELT ({start_dt[:8]} to {end_dt[:8]}, "
          f"one combined request, pool target="
          f"{gdelt_results_per_country * gdelt_overfetch_factor} per country)...")
    try:
        gdelt_articles = search_gdelt_balanced(
            query,
            plan["query_countries"],
            startdatetime=start_dt,
            enddatetime=end_dt,
            maxrecords_per_country=gdelt_results_per_country,
            overfetch_factor=gdelt_overfetch_factor,
        )
    except GDELTSearchError as exc:
        stop_reason = f"GDELT search failed: {exc} ClearFrame stopped without fallback."
        print(f"      [STOP] {stop_reason}")
        return _early_exit(
            source_title=source_title,
            article_text=article_text,
            plan=plan,
            query=query,
            article_type=article_type,
            stop_reason=stop_reason,
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

        try:
            fallback_results = search_gdelt_fallback(
                terms_query, fallback_domain, start_dt, end_dt,
                maxrecords=gdelt_results_per_country,
            )
        except GDELTSearchError as exc:
            stop_reason = f"GDELT fallback search failed: {exc} ClearFrame stopped."
            print(f"      [STOP] {stop_reason}")
            return _early_exit(
                source_title=source_title,
                article_text=article_text,
                plan=plan,
                query=query,
                article_type=article_type,
                gdelt_df=gdelt_df,
                stop_reason=stop_reason,
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
        return _early_exit(source_title=source_title, article_text=article_text,
                           plan=plan, query=query)

    candidates_df = deduplicate_candidate_metadata(gdelt_df)
    print(f"      Metadata deduplication kept {len(candidates_df)}/{len(gdelt_df)} candidate(s).")

    common = {"source_title": source_title, "article_text": article_text,
              "plan": plan, "query": query,
              "gdelt_df": gdelt_df, "article_type": article_type}

    # Stage 4: Fetch the complete candidate pool before any semantic decision.
    print(f"\n[4/9] Fetching full text for all {len(candidates_df)} metadata-unique candidate(s)...")
    fulltext_df = fetch_candidate_texts(
        candidates_df, list(range(len(candidates_df))), event_country
    )
    if fulltext_df.empty:
        print("      No candidate yielded usable full text. Exiting early.")
        return _early_exit(**common, gate_results=[])

    # Stage 5: NLP near-duplicate clustering within each source country.
    print(f"\n[5/9] Removing near-duplicate full-text articles with word-shingle similarity...")
    deduplicated_df, duplicate_clusters = remove_near_duplicate_texts(
        fulltext_df,
        body_threshold=NEAR_DUP_BODY_THRESHOLD,
        title_threshold=NEAR_DUP_TITLE_THRESHOLD,
    )
    removed_count = len(fulltext_df) - len(deduplicated_df)
    print(f"      Removed {removed_count} near-duplicate article(s); "
          f"{len(deduplicated_df)} candidate(s) remain.")

    # Stage 6: One full-text relevance judgment per deduplicated candidate.
    print(f"\n[6/9] Full-text topical gate over {len(deduplicated_df)} candidate(s)...")
    gate_results = topical_gate(article_text, deduplicated_df, article_type, client)
    metadata_by_index = {
        int(row["row_index"]): row for _, row in deduplicated_df.iterrows()
    }
    for result in gate_results:
        verdict = "PASS" if result.get("topically_relevant") else "drop"
        row = metadata_by_index.get(int(result.get("row_index", -1)), {})
        print(f"        [{verdict}] row {int(result.get('row_index', -1)):<2} "
              f"{str(row.get('domain', '?')):<28} {result.get('reason', '')}")

    passed = {r["row_index"] for r in gate_results if r.get("topically_relevant")}
    relevant_df = deduplicated_df[deduplicated_df["row_index"].isin(passed)].reset_index(drop=True)
    print(f"      {len(relevant_df)}/{len(deduplicated_df)} candidate(s) passed.")
    if relevant_df.empty:
        print("      Nothing passed the topical gate. Exiting early.")
        return _early_exit(**common, gate_results=gate_results,
                           fulltext_df=fulltext_df)

    # Stage 7: Prefer outlet breadth, then allow a second item per outlet.
    print(f"\n[7/9] Selecting a diverse set: up to {gdelt_results_per_country} per country, "
          f"at most {max_articles_per_outlet} per outlet...")
    diverse_df = select_diverse_articles(
        relevant_df,
        max_per_country=gdelt_results_per_country,
        max_per_outlet=max_articles_per_outlet,
    )
    print(f"      Selected {len(diverse_df)}/{len(relevant_df)} relevant article(s).")
    if diverse_df.empty:
        return _early_exit(**common, gate_results=gate_results,
                           fulltext_df=fulltext_df)

    # Stage 8: Chomsky pair analysis over every diverse selection.
    print(f"\n[8/9] Chomsky pair analysis over {len(diverse_df)} selected article(s)...")
    print(f"      First extracting your article once across "
          f"{len(SINGLE_ARTICLE_CATEGORIES)} single-article categories.")
    source_analysis = extract_source_article_analysis(article_text, source_url, client)
    print("      Source extraction complete. Reusing that fixed source analysis for "
          f"{', '.join(SINGLE_ARTICLE_CATEGORIES)}.")
    print("      Comparative categories are analyzed directly between your article and "
          f"each GDELT article: {', '.join(COMPARATIVE_CATEGORIES)}.")

    pair_analyses:   list[dict]      = []

    rows = [row for _, row in diverse_df.iterrows()]
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

    # Stage 9: Category synthesis, display, and debug output.
    print(f"\n[9/9] Synthesising category paragraphs from {len(pair_analyses)} pair extraction(s)...")
    synthesis = synthesize_category_paragraphs(pair_analyses, article_text, client)
    print(f"      Produced {len(synthesis.get('categories', {}))} category paragraph(s) "
          "and one concise overall summary.")

    print("      Displaying category results and writing debug dump...")
    print_user_results(synthesis)
    print_dev_results(diverse_df, pair_analyses)

    dump_path = dump_debug_run({
        "timestamp":       datetime.now(timezone.utc).isoformat(),
        "source_url":      source_url,
        "source_title":    source_title,
        "plan":            plan,
        "query":           query,
        "article_type":    article_type,
        "gate_results":    gate_results,
        "near_duplicate_clusters": duplicate_clusters,
        "fetched_text_metadata": [
            {"row_index": int(r["row_index"]), "domain": str(r.get("domain", "")),
             "url": str(r.get("url", "")), "sourcecountry": str(r.get("sourcecountry", "")),
             "query_country": str(r.get("query_country", "")),
             "is_local": bool(r.get("is_local", False)),
             "text_length": len(str(r.get("article_text", "")))}
            for _, r in fulltext_df.iterrows()
        ],
        "selected_article_metadata": [
            {"row_index": int(r["row_index"]), "domain": str(r.get("domain", "")),
             "url": str(r.get("url", "")), "sourcecountry": str(r.get("sourcecountry", ""))}
            for _, r in diverse_df.iterrows()
        ],
        "source_analysis": source_analysis,
        "pair_analyses":   pair_analyses,
        "synthesis": synthesis,
    })
    if dump_path:
        print(f"\n  [DEV] Full run dumped to: {dump_path}")

    return {
        "source_url":      source_url,
        "source_title":    source_title,
        "article_text":    article_text,
        "plan":            plan,
        "query":           query,
        "gdelt_df":        gdelt_df,
        "article_type":    article_type,
        "gate_results":    gate_results,
        "fulltext_df":     fulltext_df,
        "diverse_df":      diverse_df,
        "source_analysis": source_analysis,
        "pair_analyses":   pair_analyses,
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


