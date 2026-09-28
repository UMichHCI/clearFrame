"""Deterministic within-country article deduplication and diversity selection."""

from __future__ import annotations

import re
from collections import OrderedDict
from urllib.parse import urlparse

import pandas as pd


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _normalize_words(value: str) -> list[str]:
    return _TOKEN_RE.findall(str(value).lower())


def _normalized_title(value: str) -> str:
    return " ".join(_normalize_words(value))


def _country_key(value: str) -> str:
    return "".join(_normalize_words(value)) or "unknown"


def _outlet_key(row) -> str:
    domain = str(row.get("domain", "")).strip().lower()
    if not domain:
        domain = urlparse(str(row.get("url", ""))).netloc.lower()
    return domain.removeprefix("www.") or "unknown"


def deduplicate_candidate_metadata(candidates_df: pd.DataFrame) -> pd.DataFrame:
    """Remove repeated URLs and exact normalized titles within each country."""
    if candidates_df.empty:
        return candidates_df.copy()

    kept: list[dict] = []
    seen_urls: set[str] = set()
    seen_titles: set[tuple[str, str]] = set()

    for _, row in candidates_df.iterrows():
        url = str(row.get("url", "")).strip()
        country = _country_key(row.get("sourcecountry", ""))
        title = _normalized_title(row.get("title", ""))

        if url and url in seen_urls:
            continue
        if title and (country, title) in seen_titles:
            continue

        if url:
            seen_urls.add(url)
        if title:
            seen_titles.add((country, title))
        kept.append(row.to_dict())

    return pd.DataFrame(kept).reset_index(drop=True)


def _word_shingles(value: str, size: int = 5) -> set[tuple[str, ...]]:
    words = _normalize_words(value)
    if len(words) < size:
        return {tuple(words)} if words else set()
    return {tuple(words[i:i + size]) for i in range(len(words) - size + 1)}


def _jaccard(left: set, right: set) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def remove_near_duplicate_texts(
    fulltext_df: pd.DataFrame,
    body_threshold: float = 0.70,
    title_threshold: float = 0.85,
) -> tuple[pd.DataFrame, list[dict]]:
    """Cluster near-duplicates within each country and keep the longest article.

    Similarity uses word-shingle Jaccard scores, so no LLM or external API is
    involved. The returned cluster records make every removal auditable.
    """
    if fulltext_df.empty:
        return fulltext_df.copy(), []

    records = [row.to_dict() for _, row in fulltext_df.iterrows()]
    parents = list(range(len(records)))
    body_shingles = [_word_shingles(row.get("article_text", ""), 5) for row in records]
    title_tokens = [set(_normalize_words(row.get("title", ""))) for row in records]
    countries = [_country_key(row.get("sourcecountry", "")) for row in records]

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    for left in range(len(records)):
        for right in range(left + 1, len(records)):
            if countries[left] != countries[right]:
                continue
            body_score = _jaccard(body_shingles[left], body_shingles[right])
            title_score = _jaccard(title_tokens[left], title_tokens[right])
            if body_score >= body_threshold or (
                title_score >= title_threshold and body_score >= 0.45
            ):
                union(left, right)

    clusters: OrderedDict[int, list[int]] = OrderedDict()
    for index in range(len(records)):
        clusters.setdefault(find(index), []).append(index)

    kept_indices: list[int] = []
    cluster_report: list[dict] = []
    for members in clusters.values():
        representative = max(
            members,
            key=lambda index: (len(str(records[index].get("article_text", ""))), -index),
        )
        kept_indices.append(representative)
        if len(members) > 1:
            cluster_report.append({
                "country": str(records[representative].get("sourcecountry", "")),
                "kept_row_index": int(records[representative].get("row_index", representative)),
                "removed_row_indices": [
                    int(records[index].get("row_index", index))
                    for index in members
                    if index != representative
                ],
            })

    kept_indices.sort()
    return pd.DataFrame([records[index] for index in kept_indices]).reset_index(drop=True), cluster_report


def select_diverse_articles(
    relevant_df: pd.DataFrame,
    max_per_country: int = 10,
    max_per_outlet: int = 2,
) -> pd.DataFrame:
    """Select country-balanced articles, preferring outlet breadth first."""
    if relevant_df.empty:
        return relevant_df.copy()

    records = [row.to_dict() for _, row in relevant_df.iterrows()]
    country_groups: OrderedDict[str, list[dict]] = OrderedDict()
    for row in records:
        country_groups.setdefault(_country_key(row.get("sourcecountry", "")), []).append(row)

    selected: list[dict] = []
    for country_rows in country_groups.values():
        outlet_groups: OrderedDict[str, list[dict]] = OrderedDict()
        for row in country_rows:
            outlet_groups.setdefault(_outlet_key(row), []).append(row)

        country_selected: list[dict] = []
        for round_index in range(max_per_outlet):
            for outlet_rows in outlet_groups.values():
                if len(country_selected) >= max_per_country:
                    break
                if round_index < len(outlet_rows):
                    country_selected.append(outlet_rows[round_index])
            if len(country_selected) >= max_per_country:
                break
        selected.extend(country_selected)

    return pd.DataFrame(selected).reset_index(drop=True)
