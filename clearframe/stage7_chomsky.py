import json

from openai import OpenAI

from .config import MODEL_FULL
from .llm import api_chat, extract_json
from .prompts import (
    ARTICLE_EXTRACTION_SYSTEM,
    ARTICLE_EXTRACTION_USER_TEMPLATE,
    CATEGORY_ANALYSIS_SCHEMA,
    CATEGORY_GUIDES,
    CHOMSKY_CATEGORIES,
    COMPARATIVE_CATEGORIES,
    PAIR_DIFFERENCE_SCHEMA,
    PAIR_DIFFERENCE_SYSTEM,
    PAIR_DIFFERENCE_USER_TEMPLATE,
    SINGLE_ARTICLE_CATEGORIES,
)


def extract_source_article_analysis(base_text: str, source_url: str, client: OpenAI) -> dict:
    return extract_article_analysis(
        article_text=base_text,
        client=client,
        categories=SINGLE_ARTICLE_CATEGORIES,
        title="Your article",
        outlet="",
        source_country="",
        url=source_url,
        language="unknown",
    )


def extract_candidate_article_analysis(candidate_row, client: OpenAI) -> dict:
    return extract_article_analysis(
        article_text=str(candidate_row.get("article_text", "")),
        client=client,
        categories=SINGLE_ARTICLE_CATEGORIES,
        title=str(candidate_row.get("title", "")),
        outlet=str(candidate_row.get("domain", "")),
        source_country=str(candidate_row.get("sourcecountry", "")),
        url=str(candidate_row.get("url", "")),
        language=str(candidate_row.get("language", "unknown")),
    )


def extract_article_analysis(
    article_text: str,
    client: OpenAI,
    categories: list[str] | None = None,
    title: str = "",
    outlet: str = "",
    source_country: str = "",
    url: str = "",
    language: str = "unknown",
) -> dict:
    categories = categories or SINGLE_ARTICLE_CATEGORIES
    user_prompt = ARTICLE_EXTRACTION_USER_TEMPLATE.format(
        title=title,
        outlet=outlet,
        source_country=source_country,
        url=url,
        language=language,
        article_text=article_text[:7000],
        category_guides=json.dumps(_category_guides_for(categories), ensure_ascii=False, indent=2),
        category_schema=json.dumps(CATEGORY_ANALYSIS_SCHEMA, ensure_ascii=False, indent=2),
    )

    raw = api_chat(
        client,
        system=ARTICLE_EXTRACTION_SYSTEM,
        user=user_prompt,
        max_tokens=4000,
        model=MODEL_FULL,
        response_format={"type": "json_object"},
    )

    try:
        data = json.loads(extract_json(raw))
    except json.JSONDecodeError as e:
        print(f"      [WARNING] Article extraction returned unparseable JSON: {e}")
        data = {}

    return _clean_category_answers(data.get("category_answers", {}), categories)


def chomsky_pair_analysis(source_text: str, source_answers: dict, candidate_row, client: OpenAI) -> dict:
    row_index = int(candidate_row.get("row_index", 0))
    article_reference = {
        "title": str(candidate_row.get("title", "")),
        "outlet": str(candidate_row.get("domain", "")),
        "source_country": str(candidate_row.get("sourcecountry", "")),
        "url": str(candidate_row.get("url", "")),
    }

    comparison_answers = extract_candidate_article_analysis(candidate_row, client)

    user_prompt = PAIR_DIFFERENCE_USER_TEMPLATE.format(
        row_index=row_index,
        article_reference=json.dumps(article_reference, ensure_ascii=False, indent=2),
        single_categories=json.dumps(SINGLE_ARTICLE_CATEGORIES, ensure_ascii=False, indent=2),
        comparative_categories=json.dumps(COMPARATIVE_CATEGORIES, ensure_ascii=False, indent=2),
        source_answers=json.dumps(source_answers, ensure_ascii=False, indent=2),
        comparison_answers=json.dumps(comparison_answers, ensure_ascii=False, indent=2),
        source_text=source_text[:7000],
        cand_title=article_reference["title"],
        cand_domain=article_reference["outlet"],
        cand_country=article_reference["source_country"],
        cand_url=article_reference["url"],
        cand_language=str(candidate_row.get("language", "unknown")),
        comparison_text=str(candidate_row.get("article_text", ""))[:7000],
        comparative_guides=json.dumps(_category_guides_for(COMPARATIVE_CATEGORIES), ensure_ascii=False, indent=2),
        category_schema=json.dumps(CATEGORY_ANALYSIS_SCHEMA, ensure_ascii=False, indent=2),
        difference_schema=json.dumps(PAIR_DIFFERENCE_SCHEMA, ensure_ascii=False, indent=2),
    )

    raw = api_chat(
        client,
        system=PAIR_DIFFERENCE_SYSTEM,
        user=user_prompt,
        max_tokens=4500,
        model=MODEL_FULL,
        response_format={"type": "json_object"},
    )

    try:
        data = json.loads(extract_json(raw))
    except json.JSONDecodeError as e:
        print(f"      [WARNING] Pair extraction returned unparseable JSON for row {row_index}: {e}")
        data = {}

    return {
        "row_index": row_index,
        "article_reference": data.get("article_reference") if isinstance(data.get("article_reference"), dict) else article_reference,
        "category_answers": _clean_pair_category_answers(
            data.get("category_answers", {}),
            source_answers,
            comparison_answers,
        ),
    }


def _clean_category_answers(category_answers: dict, categories: list[str] | None = None) -> dict:
    cleaned: dict[str, dict] = {}
    if not isinstance(category_answers, dict):
        category_answers = {}

    for category in (categories or CHOMSKY_CATEGORIES):
        answer = category_answers.get(category, {})
        cleaned[category] = _clean_article_category(answer)
    return cleaned


def _category_guides_for(categories: list[str]) -> dict:
    return {
        category: CATEGORY_GUIDES[category]
        for category in categories
        if category in CATEGORY_GUIDES
    }


def _clean_article_category(answer) -> dict:
    if not isinstance(answer, dict):
        answer = {}
    evidence = answer.get("evidence", [])
    if not isinstance(evidence, list):
        evidence = []
    observations = answer.get("observations", [])
    if not isinstance(observations, list):
        observations = []
    applies = _as_bool(answer.get("applies", False))
    analysis = str(answer.get("analysis", "")).strip()
    if not applies:
        analysis = ""
        observations = []
        evidence = []
    return {
        "applies": applies,
        "analysis": analysis,
        "observations": observations,
        "evidence": [item for item in evidence if isinstance(item, dict)],
    }


def _clean_pair_category_answers(
    category_answers: dict,
    source_answers: dict,
    comparison_answers: dict,
) -> dict:
    if not isinstance(category_answers, dict):
        category_answers = {}

    cleaned: dict[str, dict] = {}
    for category in CHOMSKY_CATEGORIES:
        answer = category_answers.get(category, {})
        if not isinstance(answer, dict):
            answer = {}
        source_basis = answer.get("source_basis", [])
        if not isinstance(source_basis, list):
            source_basis = []
        comparison_basis = answer.get("comparison_basis", [])
        if not isinstance(comparison_basis, list):
            comparison_basis = []
        if category in SINGLE_ARTICLE_CATEGORIES:
            source_article = source_answers.get(category, {}) if isinstance(source_answers, dict) else {}
            comparison_article = comparison_answers.get(category, {}) if isinstance(comparison_answers, dict) else {}
        else:
            source_article = _clean_article_category(answer.get("source_article", {}))
            comparison_article = _clean_article_category(answer.get("comparison_article", {}))

        cleaned[category] = {
            "source_article": source_article,
            "comparison_article": comparison_article,
            "meaningful_difference": _as_bool(answer.get("meaningful_difference", False)),
            "difference": str(answer.get("difference", "")).strip(),
            "underlying_presupposition": str(answer.get("underlying_presupposition", "")).strip(),
            "doctrinal_boundary": str(answer.get("doctrinal_boundary", "")).strip(),
            "comparison_revelation": str(answer.get("comparison_revelation", "")).strip(),
            "interest_alignment": str(answer.get("interest_alignment", "")).strip(),
            "inference_strength": _clean_inference_strength(answer.get("inference_strength", "low")),
            "source_basis": source_basis,
            "comparison_basis": comparison_basis,
        }
    return cleaned


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1"}
    return bool(value)


def _clean_inference_strength(value) -> str:
    strength = str(value).strip().lower()
    return strength if strength in {"high", "moderate", "low"} else "low"


