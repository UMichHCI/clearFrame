import pandas as pd

from .config import STRUCTURAL_NOTE
from .prompts import CHOMSKY_CATEGORIES
from .stage8_selection import CATEGORY_PLAIN_LABELS


def print_user_results(category_synthesis: dict) -> None:
    """Print final category paragraphs. No rankings or scores."""
    print(f"\n{'='*70}")
    print("  WHAT THE COMPARISON ARTICLES REVEAL")
    print(f"{'='*70}\n")

    summary = category_synthesis.get("summary", "").strip() if isinstance(category_synthesis, dict) else ""
    summary_articles = category_synthesis.get("summary_supporting_articles", []) if isinstance(category_synthesis, dict) else []
    categories = category_synthesis.get("categories", {}) if isinstance(category_synthesis, dict) else {}
    if summary:
        print(summary)
        if summary_articles:
            print("References:")
            for article in summary_articles:
                title = str(article.get("title", "Untitled"))
                outlet = str(article.get("outlet", ""))
                country = str(article.get("source_country", ""))
                url = str(article.get("url", ""))
                source = country or outlet
                print(f"  - {title} ({source}) {url}".rstrip())
        print()
    if not categories:
        if not summary:
            print("No meaningful category-level differences surfaced for this story.")
        print(f"\n{STRUCTURAL_NOTE}")
        print(f"{'='*70}")
        return

    print("CATEGORY DETAILS")
    for category in CHOMSKY_CATEGORIES:
        item = categories.get(category)
        if not isinstance(item, dict):
            continue
        label = CATEGORY_PLAIN_LABELS.get(category, category.replace("_", " "))
        print(f"\n{label.upper()}")
        print(item.get("paragraph", ""))
        articles = item.get("supporting_articles", [])
        if articles:
            print("  References:")
            for article in articles:
                title = str(article.get("title", "Untitled"))
                outlet = str(article.get("outlet", ""))
                url = str(article.get("url", ""))
                print(f"  - {title} ({outlet}) {url}".rstrip())

    print(f"\n{category_synthesis.get('structural_note', STRUCTURAL_NOTE)}")
    print(f"\n{'='*70}")


def print_dev_results(fulltext_df: pd.DataFrame, pair_analyses: list[dict]) -> None:
    """Verbose developer output for every extracted pair."""
    print(f"\n{'='*70}")
    print("  [DEV] FULL PAIR EXTRACTIONS - NOT USER-FACING")
    print(f"{'='*70}")

    if not pair_analyses:
        print("\n  [DEV] No pair extractions were produced.")
        return

    meta = {int(r["row_index"]): r for _, r in fulltext_df.iterrows()} if not fulltext_df.empty else {}

    for pa in sorted(pair_analyses, key=lambda p: p.get("row_index", 0)):
        idx = int(pa.get("row_index", -1))
        row = meta.get(idx, {})
        ref = pa.get("article_reference", {}) if isinstance(pa.get("article_reference"), dict) else {}
        domain = str(ref.get("outlet") or row.get("domain", "unknown"))

        print(f"\n{'-'*70}")
        print(f"  [DEV] row {idx} - {domain} - {row.get('sourcecountry', '?')}")
        print(f"        {str(ref.get('title') or row.get('title', ''))[:90]}")

        answers = pa.get("category_answers", {})
        print("\n        extracted category answers:")
        for category in CHOMSKY_CATEGORIES:
            answer = answers.get(category, {}) if isinstance(answers, dict) else {}
            comparison = answer.get("comparison_article", {}) if isinstance(answer, dict) else {}
            applies = bool(answer.get("meaningful_difference")) or (
                isinstance(comparison, dict) and bool(comparison.get("applies"))
            )
            print(f"          {category}: {'populated' if applies else 'empty'}")

    print(f"\n{'='*70}")

