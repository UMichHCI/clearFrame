import json

from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import OpenAI

from .config import MODEL_FULL, STRUCTURAL_NOTE
from .llm import api_chat, extract_json
from .prompts import CATEGORY_SYNTHESIS_SYSTEM, CHOMSKY_CATEGORIES, OVERALL_SUMMARY_SYSTEM


CATEGORY_SYNTHESIS_MAX_WORKERS = 6


def synthesize_category_paragraphs(pair_analyses: list[dict], base_text: str,
                                   client: OpenAI) -> dict:
    """Synthesize every eligible category independently and record all decisions."""
    decisions = _empty_category_decisions("No meaningful pair evidence was found.")
    eligible = {
        category: _meaningful_extractions(pair_analyses, category)
        for category in CHOMSKY_CATEGORIES
    }
    eligible = {category: rows for category, rows in eligible.items() if rows}

    if eligible:
        label = "category" if len(eligible) == 1 else "categories"
        print(f"      Synthesizing {len(eligible)} eligible {label} independently...")
        worker_count = min(CATEGORY_SYNTHESIS_MAX_WORKERS, len(eligible))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(
                    _synthesize_one_category, category, rows, base_text, client
                ): category
                for category, rows in eligible.items()
            }
            for future in as_completed(futures):
                category = futures[future]
                try:
                    decisions[category] = future.result()
                except Exception as exc:
                    print(f"      [WARNING] {category} synthesis failed: {exc}")
                    decisions[category] = _excluded_decision(f"Synthesis failed: {exc}")

    cleaned_categories = {
        category: {
            "doctrinal_claim": decision["doctrinal_claim"],
            "paragraph": decision["paragraph"],
            "examples": decision["examples"],
            "supporting_articles": decision["supporting_articles"],
        }
        for category, decision in decisions.items()
        if decision["include"]
    }
    overall = synthesize_overall_summary(cleaned_categories, client)

    return {
        "summary": overall.get("summary", ""),
        "summary_supporting_articles": overall.get("supporting_articles", []),
        "categories": cleaned_categories,
        "category_decisions": decisions,
        "structural_note": STRUCTURAL_NOTE,
    }


def _meaningful_extractions(pair_analyses: list[dict], category: str) -> list[dict]:
    rows = []
    for pair in pair_analyses or []:
        if not isinstance(pair, dict):
            continue
        answers = pair.get("category_answers", {})
        answer = answers.get(category) if isinstance(answers, dict) else None
        if not isinstance(answer, dict) or not _as_bool(answer.get("meaningful_difference")):
            continue
        rows.append({
            "row_index": pair.get("row_index"),
            "article_reference": pair.get("article_reference", {}),
            "category_answer": answer,
        })
    return rows


def _synthesize_one_category(category: str, pair_extractions: list[dict],
                             base_text: str, client: OpenAI) -> dict:
    payload = json.dumps({
        "category": category,
        "base_article_excerpt": base_text[:3000],
        "meaningful_pair_extractions": pair_extractions,
    }, ensure_ascii=False, default=str)
    raw = api_chat(
        client,
        system=CATEGORY_SYNTHESIS_SYSTEM,
        user=payload,
        max_tokens=1400,
        model=MODEL_FULL,
        response_format={"type": "json_object"},
    )
    return _clean_category_decision(json.loads(extract_json(raw)))


def synthesize_overall_summary(categories: dict, client: OpenAI) -> dict:
    """Combine included category paragraphs into one concise summary."""
    if not categories:
        return {"summary": "", "supporting_articles": []}

    payload = json.dumps({"categories": categories}, ensure_ascii=False, default=str)
    try:
        raw = api_chat(
            client,
            system=OVERALL_SUMMARY_SYSTEM,
            user=payload,
            max_tokens=700,
            model=MODEL_FULL,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(extract_json(raw))
        return _clean_overall_summary(parsed)
    except Exception as e:
        print(f"      [WARNING] Overall summary failed: {e}")
        return {"summary": "", "supporting_articles": []}


def _empty_category_decisions(reason: str) -> dict:
    return {category: _excluded_decision(reason) for category in CHOMSKY_CATEGORIES}


def _excluded_decision(reason: str) -> dict:
    return {
        "include": False,
        "doctrinal_claim": "",
        "paragraph": "",
        "examples": [],
        "supporting_articles": [],
        "exclusion_reason": reason,
    }


def _clean_category_decision(value: dict) -> dict:
    if not isinstance(value, dict) or not _as_bool(value.get("include")):
        reason = value.get("exclusion_reason", "") if isinstance(value, dict) else ""
        return _excluded_decision(
            str(reason).strip() or "The category did not meet the inclusion threshold."
        )

    paragraph = str(value.get("paragraph", "")).strip()
    if not paragraph:
        return _excluded_decision("The synthesis response did not contain a paragraph.")

    articles = value.get("supporting_articles", [])
    if not isinstance(articles, list):
        articles = []
    articles = [article for article in articles if isinstance(article, dict)]

    examples = value.get("examples", [])
    if not isinstance(examples, list):
        examples = []
    examples = [
        _reader_text(str(example).strip())
        for example in examples
        if str(example).strip()
    ]

    claim = _reader_text(str(value.get("doctrinal_claim", "")).strip())
    return {
        "include": True,
        "doctrinal_claim": claim,
        "paragraph": _replace_outlets_with_countries(
            _reader_text(paragraph), articles
        ),
        "examples": [
            _replace_outlets_with_countries(example, articles)
            for example in examples
        ],
        "supporting_articles": articles,
        "exclusion_reason": "",
    }


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1"}
    return bool(value)


def _clean_overall_summary(value: dict) -> dict:
    if not isinstance(value, dict):
        return {"summary": "", "supporting_articles": []}

    articles = value.get("supporting_articles", [])
    if not isinstance(articles, list):
        articles = []
    articles = [a for a in articles if isinstance(a, dict)]

    summary = _reader_text(str(value.get("summary", "")).strip())
    return {
        "summary": _replace_outlets_with_countries(summary, articles),
        "supporting_articles": articles,
    }


def _reader_text(text: str) -> str:
    replacements = {
        "the source article": "your article",
        "The source article": "Your article",
        "the base article": "your article",
        "The base article": "Your article",
        "the original article": "your article",
        "The original article": "Your article",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _replace_outlets_with_countries(text: str, articles: list[dict]) -> str:
    for article in articles:
        outlet = str(article.get("outlet", "")).strip()
        country = str(article.get("source_country", "")).strip()
        if outlet and country:
            text = text.replace(outlet, country)
    return text

