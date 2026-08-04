import pandas as pd

from .config import STRUCTURAL_NOTE
from .stage7_chomsky import CHOMSKY_CATEGORIES
from .stage8_selection import CATEGORY_PLAIN_LABELS, score_illumination
def print_user_results(selected_df: pd.DataFrame, synthesis: dict) -> None:
    """Short, plain-language output. No scores, no category names, no jargon."""
    print(f"\n{'='*70}")
    print("  WHAT THESE ARTICLES TOGETHER LET YOU SEE")
    print(f"{'='*70}\n")

    overall = synthesis.get("overall_synthesis", "").strip()
    print(overall if overall else "(no synthesis available)")

    print(f"\n{synthesis.get('structural_note', STRUCTURAL_NOTE)}")

    if selected_df.empty:
        print("\nNo comparison articles surfaced for this story.")
        print(f"{'='*70}")
        return

    print(f"\n{'â”€'*70}")
    print("  ARTICLES")
    print(f"{'â”€'*70}")

    for i, (_, row) in enumerate(selected_df.iterrows(), start=1):
        lens = CATEGORY_PLAIN_LABELS.get(row.get("strongest_category", ""), "")
        print(f"\n  #{i}  {row.get('title', 'N/A')}")
        print(f"      {row.get('domain', 'N/A')} Â· {row.get('sourcecountry', 'N/A')}")
        if lens:
            print(f"      Lens: {lens}")
        print(f"      {row.get('why_this_article', '')}")
        print(f"      {row.get('url', '')}")

    print(f"\n{'='*70}")


def print_dev_results(fulltext_df: pd.DataFrame, pair_analyses: list[dict],
                      outlet_contexts: dict, selected_row_indices: set) -> None:
    """
    Verbose developer output for EVERY analysed pair, selected or not:
    full category table, evidence quotes, counterfactual checks, score breakdown,
    and the backend-only outlet context.
    """
    print(f"\n{'='*70}")
    print("  [DEV] FULL PAIR ANALYSIS â€” NOT USER-FACING")
    print(f"{'='*70}")

    if not pair_analyses:
        print("\n  [DEV] No pair analyses were produced.")
        return

    meta = {int(r["row_index"]): r for _, r in fulltext_df.iterrows()} if not fulltext_df.empty else {}

    for pa in sorted(pair_analyses, key=lambda p: p.get("row_index", 0)):
        idx        = int(pa.get("row_index", -1))
        row        = meta.get(idx, {})
        domain     = str(row.get("domain", "unknown"))
        categories = pa.get("categories", {})
        score, breakdown = score_illumination(categories)
        status     = "SELECTED" if idx in selected_row_indices else "not selected"

        print(f"\n{'â”€'*70}")
        print(f"  [DEV] row {idx} Â· {domain} Â· {row.get('sourcecountry', '?')} Â· {status}")
        print(f"        {str(row.get('title', ''))[:70]}")
        print(f"        illumination score: {score}")

        ctx = outlet_contexts.get(domain, {})
        print("\n        [BACKEND ONLY â€” never shown to users] outlet context:")
        print(f"          ownership          : {ctx.get('ownership_summary', 'unknown')}")
        print(f"          state relationship : {ctx.get('state_relationship', 'unknown')}")
        print(f"          model confidence   : {ctx.get('confidence', 'unknown')}")

        print("\n        score breakdown:")
        if breakdown:
            for b in breakdown:
                print(f"          {b['category']:<26} {b['confidence']:<7} "
                      f"{b['conf_weight']} Ã— {b['cat_weight']} = {b['points']}")
            print(f"          {'TOTAL':<26} {' '*7} {' '*9} {score}")
        else:
            print("          (no categories applied â€” score 0)")

        print("\n        categories:")
        for name in CHOMSKY_CATEGORIES:
            cat = categories.get(name, {"applies": False})
            if not cat.get("applies"):
                demoted = cat.get("_demoted")
                suffix  = f"  [demoted: {demoted}]" if demoted else ""
                print(f"          {name:<26} applies: False{suffix}")
                continue
            print(f"          {name:<26} applies: True  ({cat.get('confidence')})")
            print(f"            finding    : {cat.get('finding', '')}")
            for q in cat.get("evidence_base", []):
                print(f"            base quote : \"{q}\"")
            for q in cat.get("evidence_candidate", []):
                print(f"            cand quote : \"{q}\"")
            print(f"            swap test  : {cat.get('counterfactual_check', '')}")

        print(f"\n        why_this_article: {pa.get('why_this_article', '')}")

    print(f"\n{'='*70}")

