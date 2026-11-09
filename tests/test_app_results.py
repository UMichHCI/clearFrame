import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

import app
from app import _summarize_result


class ResultArticleTests(unittest.TestCase):
    def test_summary_lists_source_and_each_unique_analyzed_article(self):
        result = {
            "source_url": "https://source.example/story",
            "source_title": "Source headline",
            "plan": {"original_source_country": "Source Country"},
            "synthesis": {"summary": "Summary", "categories": {}},
            "pair_analyses": [
                {"article_reference": {
                    "title": "First comparison",
                    "outlet": "one.example",
                    "source_country": "Country One",
                    "url": "https://one.example/story",
                }},
                {"article_reference": {
                    "title": "Duplicate reference",
                    "outlet": "one.example",
                    "source_country": "Country One",
                    "url": "https://one.example/story",
                }},
                {"article_reference": {
                    "title": "Second comparison",
                    "outlet": "two.example",
                    "source_country": "Country Two",
                    "url": "https://two.example/story",
                }},
            ],
        }

        articles = _summarize_result(result)["analysis_articles"]

        self.assertEqual([article["role"] for article in articles], [
            "source", "comparison", "comparison"
        ])
        self.assertEqual([article["url"] for article in articles], [
            "https://source.example/story",
            "https://one.example/story",
            "https://two.example/story",
        ])
        self.assertEqual(articles[0]["title"], "Source headline")
        self.assertEqual(articles[0]["source_country"], "Source Country")


class SavedResultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.root = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_results_route_uses_the_same_app_as_home(self):
        with patch.object(app, "AUTH_PASSWORD", ""):
            with urlopen(self.root + "/") as response:
                home = response.read()
            for route in ("/results", "/results/"):
                with urlopen(self.root + route) as response:
                    self.assertEqual(response.read(), home)
            self.assertIn(b'id="form"', home)
            self.assertIn(b'id="results"', home)
            self.assertNotIn(b"View results page", home)

    def test_api_restores_current_json_instead_of_the_html_export(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.json"
            with patch.object(app, "RESULTS_JSON_PATH", path), patch.object(app, "AUTH_PASSWORD", ""):
                for summary in ("First comparison", "Updated comparison"):
                    path.write_text(json.dumps({"summary": summary}), encoding="utf-8")
                    with urlopen(self.root + "/api/results") as response:
                        self.assertEqual(json.load(response), {"summary": summary})
                        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_no_saved_comparison_returns_null(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(app, "RESULTS_JSON_PATH", Path(directory) / "missing.json"), patch.object(app, "AUTH_PASSWORD", ""):
                with urlopen(self.root + "/api/results") as response:
                    self.assertIsNone(json.load(response))

    def test_invalid_snapshot_returns_a_recoverable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.json"
            path.write_text("{", encoding="utf-8")
            with patch.object(app, "RESULTS_JSON_PATH", path), patch.object(app, "AUTH_PASSWORD", ""):
                with self.assertRaises(HTTPError) as raised:
                    urlopen(self.root + "/api/results")
                self.assertEqual(raised.exception.code, 503)
                self.assertIn("error", json.load(raised.exception))
                raised.exception.close()

    def test_saved_results_require_the_app_password(self):
        with patch.object(app, "AUTH_PASSWORD", "test-password"):
            with self.assertRaises(HTTPError) as raised:
                urlopen(self.root + "/api/results")
            self.assertEqual(raised.exception.code, 401)
            raised.exception.close()


if __name__ == "__main__":
    unittest.main()
