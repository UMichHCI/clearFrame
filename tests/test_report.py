from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import queue
import tempfile
import unittest
from unittest.mock import patch

from app import stream_pipeline
from clearframe.report import render_results_html, write_results_html


class TextReader(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []

    def handle_data(self, text):
        self.text.append(text)


class ReportTests(unittest.TestCase):
    def test_completed_web_runs_replace_json_and_html_with_matching_results(self):
        with tempfile.TemporaryDirectory() as directory:
            json_path = Path(directory) / "results.json"
            html_path = Path(directory) / "results-preview.html"
            with patch("app.RESULTS_JSON_PATH", json_path), patch("app.RESULTS_HTML_PATH", html_path):
                for headline, summary, stop in (
                    ("First headline", "First summary", ""),
                    ("Second headline", "Second summary", ""),
                    ("Stopped headline", "", "No comparison articles found."),
                ):
                    raw_result = {
                        "source_url": "https://source.example/story",
                        "source_title": headline,
                        "synthesis": {"summary": summary, "categories": {}},
                        "stop_reason": stop,
                    }
                    sink = queue.Queue()
                    with patch("app.run_clearframe_pipeline", return_value=raw_result):
                        stream_pipeline("https://source.example/story", "test-key", sink)
                    stored = json.loads(json_path.read_text(encoding="utf-8"))
                    html = html_path.read_text(encoding="utf-8")
                    self.assertIn(headline, html)
                    self.assertEqual(stored["summary"], summary)
                    self.assertIn(summary or stop, html)
                    self.assertNotIn("llm_analysis", stored)
                    self.assertNotIn("test-key", html)
                self.assertNotIn("First summary", html)
                self.assertNotIn("Second summary", html)
                self.assertIn("Analysis stopped", html)

    def test_report_preserves_findings_and_safe_links_without_source_map(self):
        paragraph = 'Your article blames A. Another article questions that claim. <Keep this qualification> & uncertainty.'
        data = {
            "summary": "A summary with <script> & punctuation.",
            "structural_note": "A note.",
            "categories": [{
                "key": "agency_attribution", "label": "Agency Attribution",
                "paragraph": paragraph,
                "supporting_articles": [
                    {"title": "Valid source", "url": "https://source.example/?a=1&b=2"},
                    {"title": "Unsafe link", "url": "javascript:alert(1)"},
                ],
            }],
        }
        html = render_results_html(data)
        parser = TextReader()
        parser.feed(html)
        self.assertIn(paragraph, "".join(parser.text))
        self.assertIn(escape(data["summary"]), html)
        self.assertIn('href="https://source.example/?a=1&amp;b=2"', html)
        self.assertNotIn('href="javascript:', html)
        self.assertNotIn("<script", html)
        self.assertNotIn("Where the findings draw support", html)
        self.assertNotIn("source-map", html)
        self.assertNotIn("<link", html)

    def test_command_line_result_can_generate_the_same_report(self):
        comparison = {
            "title": "Comparison", "url": "https://comparison.example/story",
            "source_country": "Oman", "outlet": "comparison.example",
        }
        result = {
            "source_url": "https://source.example/story", "source_title": "Source headline",
            "plan": {"original_source_country": "United States"},
            "synthesis": {"summary": "Summary", "categories": {
                "agency_attribution": {"paragraph": "A finding.", "supporting_articles": [comparison]},
            }},
            "pair_analyses": [{"article_reference": comparison}, {"article_reference": comparison}],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.html"
            write_results_html(result, path)
            html = path.read_text(encoding="utf-8")
        for text in ("Source headline", "Summary", "Agency Attribution", "A finding.", "Oman"):
            self.assertIn(text, html)
        self.assertIn("1 comparison articles", html)
        self.assertIn("2 publishing countries", html)


if __name__ == "__main__":
    unittest.main()
