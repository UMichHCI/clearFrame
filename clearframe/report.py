"""Build a standalone reading copy of the Results tab, without network dependencies."""

from collections import defaultdict
from html import escape
from pathlib import Path
import re
from urllib.parse import urlparse

from .prompts import CATEGORY_PLAIN_LABELS


REPORT_PATH = Path(__file__).resolve().parent.parent / "results-preview.html"
REPORT_STYLE_PATH = Path(__file__).resolve().parent.parent / "static" / "report.css"


def _text(value) -> str:
    return escape(str(value or ""), quote=True)


def _article_link(article: dict) -> str:
    title = _text(article.get("title") or "Untitled article")
    url = str(article.get("url") or "").strip()
    try:
        valid = urlparse(url).scheme in {"http", "https"} and bool(urlparse(url).netloc)
    except ValueError:
        valid = False
    if valid:
        return f'<a href="{_text(url)}" target="_blank" rel="noopener noreferrer">{title}</a>'
    return title


def _article_list(articles: list[dict]) -> str:
    items = []
    for article in articles:
        metadata = " / ".join(filter(None, [
            str(article.get("source_country") or ""),
            str(article.get("outlet") or ""),
        ]))
        items.append(
            f'<li>{_article_link(article)}'
            f'<span class="article-meta">{_text(metadata)}</span></li>'
        )
    return '<ul class="article-list">' + "".join(items) + '</ul>'


def _pipeline_report_data(result: dict) -> dict:
    """Adapt a command-line pipeline result to the same report fields as the web UI."""
    synthesis = result.get("synthesis") or {}
    categories = [
        {"key": key, "label": CATEGORY_PLAIN_LABELS.get(key, key.replace("_", " ")), **item}
        for key, item in (synthesis.get("categories") or {}).items()
        if isinstance(item, dict)
    ]
    articles = []
    if result.get("source_url"):
        articles.append({
            "title": result.get("source_title") or "Your article",
            "url": result["source_url"],
            "source_country": (result.get("plan") or {}).get("original_source_country", ""),
            "role": "source",
        })
    seen = {article["url"] for article in articles}
    for pair in result.get("pair_analyses") or []:
        article = pair.get("article_reference") or {}
        url = article.get("url")
        if url and url not in seen:
            articles.append({**article, "role": "comparison"})
            seen.add(url)
    return {
        "summary": synthesis.get("summary", ""),
        "structural_note": synthesis.get("structural_note", ""),
        "stop_reason": result.get("stop_reason", ""),
        "categories": categories,
        "analysis_articles": articles,
    }


def render_results_html(data: dict) -> str:
    categories = data.get("categories") or []
    articles = data.get("analysis_articles") or []
    source = next((a for a in articles if a.get("role") == "source"), None)
    comparisons = [a for a in articles if a.get("role") != "source"]
    countries = {a.get("source_country") for a in articles if a.get("source_country")}
    title = source.get("title") if source else "Coverage comparison"
    contents = []
    findings = []
    for number, category in enumerate(categories, 1):
        label = category.get("label") or CATEGORY_PLAIN_LABELS.get(
            category.get("key"), "Finding"
        )
        contents.append(f'<li><a href="#finding-{number}">{number}. {_text(label)}</a></li>')
        paragraph = str(category.get("paragraph") or "")
        split = re.search(r"(?<=[.!?])\s+(?=[A-Z])", paragraph)
        if split:
            body = f'<strong>{_text(paragraph[:split.start()])}</strong> {_text(paragraph[split.end():])}'
        else:
            body = f'<strong>{_text(paragraph)}</strong>'
        references = category.get("supporting_articles") or []
        evidence = (
            '<div class="references"><h4>Supporting articles</h4>'
            + _article_list(references) + '</div>'
        ) if references else ""
        findings.append(
            f'<section class="finding" id="finding-{number}" aria-labelledby="heading-{number}">'
            f'<h3 id="heading-{number}"><span class="number">{number:02}</span> {_text(label)}</h3>'
            f'<p>{body}</p>{evidence}</section>'
        )
    if not findings:
        findings.append('<p class="empty">The comparison did not find clear evidence of an important difference in how these articles explain the story.</p>')
    grouped = defaultdict(list)
    for article in comparisons:
        grouped[article.get("source_country") or "Unknown country"].append(article)
    library = "".join(
        f'<details class="country"><summary>{_text(country)} <span>({len(items)})</span></summary>'
        + _article_list(items) + '</details>'
        for country, items in sorted(grouped.items())
    )
    library_section = (
        '<section class="library" id="articles"><h2>Articles compared</h2>'
        '<p class="section-note">All comparison articles, grouped by publishing country. '
        'Not every article contributes to a final finding.</p>' + library + '</section>'
    ) if comparisons else ""
    source_link = _article_link(source) if source else _text(title)
    source_country = _text(source.get("source_country")) if source else ""
    stop = (
        '<section class="stop"><h2>Analysis stopped</h2>'
        f'<p>{_text(data["stop_reason"])}</p></section>'
    ) if data.get("stop_reason") else ""
    summary = (
        '<section class="overview" id="overview" aria-labelledby="overview-heading">'
        '<h2 id="overview-heading">Overall summary</h2>'
        f'<p>{_text(data["summary"])}</p></section>'
    ) if data.get("summary") else ""
    navigation = (
        '<nav class="contents" aria-label="Findings"><h2>In this comparison</h2>'
        '<ol>' + "".join(contents) + '</ol></nav>'
    ) if contents else ""
    note = f'<p>{_text(data["structural_note"])}</p>' if data.get("structural_note") else ""
    css = REPORT_STYLE_PATH.read_text(encoding="utf-8")
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ClearFrame: {_text(title)}</title>
<meta name="description" content="ClearFrame results: analysis, category findings, and supporting articles.">
<style>{css}</style>
</head>
<body>
<a class="skip" href="#main">Skip to results</a>
<div class="page">
<header class="masthead"><a href="#main" class="brand">ClearFrame</a><span>Coverage analysis</span></header>
<main id="main">
<header class="report-heading"><p class="kicker">Your article</p><h1>{source_link}</h1>
<p class="source-country">{source_country}</p>
<p class="scope">{len(comparisons)} comparison articles <span aria-hidden="true">/</span>
{len(countries)} publishing countries <span aria-hidden="true">/</span> {len(categories)} findings</p></header>
{stop}{summary}{navigation}
<section class="findings" aria-labelledby="findings-heading"><h2 id="findings-heading">Category findings</h2>{''.join(findings)}</section>
{library_section}
</main>
<footer>{note}<p>Saved results. This file is replaced after each completed run.</p></footer>
</div>
</body>
</html>
'''


def write_results_html(data: dict, path: str | Path = REPORT_PATH) -> None:
    if "synthesis" in data:
        data = _pipeline_report_data(data)
    html = render_results_html(data)
    Path(path).write_text(html, encoding="utf-8")
