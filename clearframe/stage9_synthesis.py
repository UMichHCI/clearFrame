import json

from openai import OpenAI

from .config import MODEL_FULL, STRUCTURAL_NOTE
from .llm import api_chat, extract_json
from .prompts import CATEGORY_SYNTHESIS_SYSTEM, CHOMSKY_CATEGORIES, OVERALL_SUMMARY_SYSTEM


def synthesize_category_paragraphs(pair_analyses: list[dict], base_text: str,
                                   client: OpenAI) -> dict:
    """
    Final category-level synthesis. The model decides which categories have a
    meaningful difference and writes one paragraph per included category.
    """
    if not pair_analyses:
        return {"categories": {}, "structural_note": STRUCTURAL_NOTE}

    payload = json.dumps({
        "base_article_excerpt": base_text[:3000],
        "allowed_categories": CHOMSKY_CATEGORIES,
        "pair_extractions": pair_analyses,
    }, ensure_ascii=False, default=str)

    try:
        raw = api_chat(
            client,
            system=CATEGORY_SYNTHESIS_SYSTEM,
            user=payload,
            max_tokens=3500,
            model=MODEL_FULL,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(extract_json(raw))
        categories = parsed.get("categories", {})
    except Exception as e:
        print(f"      [WARNING] Category synthesis failed: {e}")
        categories = {}

    cleaned_categories = _clean_category_summaries(categories)
    overall = synthesize_overall_summary(cleaned_categories, client)

    return {
        "summary": overall.get("summary", ""),
        "summary_supporting_articles": overall.get("supporting_articles", []),
        "categories": cleaned_categories,
        "structural_note": STRUCTURAL_NOTE,
    }


def synthesize_overall_summary(categories: dict, client: OpenAI) -> dict:
    """
    Third LLM call: combine included category paragraphs into one concise summary.
    """
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


def _clean_category_summaries(categories: dict) -> dict:
    if not isinstance(categories, dict):
        return {}

    cleaned: dict[str, dict] = {}
    for category in CHOMSKY_CATEGORIES:
        value = categories.get(category)
        if not isinstance(value, dict):
            continue
        paragraph = str(value.get("paragraph", "")).strip()
        if not paragraph:
            continue
        doctrinal_claim = str(value.get("doctrinal_claim", "")).strip()
        examples = value.get("examples", [])
        if not isinstance(examples, list):
            examples = []
        examples = [_reader_text(str(example).strip()) for example in examples if str(example).strip()]
        articles = value.get("supporting_articles", [])
        if not isinstance(articles, list):
            articles = []
        articles = [a for a in articles if isinstance(a, dict)]
        cleaned[category] = {
            "doctrinal_claim": _reader_text(doctrinal_claim),
            "paragraph": _replace_outlets_with_countries(_reader_text(paragraph), articles),
            "examples": [_replace_outlets_with_countries(example, articles) for example in examples],
            "supporting_articles": articles,
        }
    return cleaned


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

