import unittest
from unittest.mock import Mock, patch

from clearframe.stage3_gdelt_search import GDELTSearchError, search_gdelt, search_gdelt_balanced


class GDELTSearchTests(unittest.TestCase):
    def test_selected_country_names_match_returned_country_names(self):
        payload = {"articles": [
            {"url": "https://example.com/gaza", "sourcecountry": "Gaza Strip"},
            {"url": "https://example.com/westbank", "sourcecountry": "West Bank"},
            {"url": "https://example.com/israel", "sourcecountry": "Israel"},
            {"url": "https://example.com/other", "sourcecountry": "France"},
        ]}
        with patch("clearframe.stage3_gdelt_search.search_gdelt", return_value=payload):
            articles = search_gdelt_balanced("query", ["Gaza Strip", "West Bank", "Israel"],
                                            "20200101000000", "20200103235959")
        self.assertEqual([a["query_country"] for a in articles], ["Gaza Strip", "West Bank", "Israel"])

    def test_persistent_rate_limit_raises_after_ten_attempts(self):
        response = Mock(status_code=429, text="rate limited")

        with (
            patch("clearframe.stage3_gdelt_search.requests.get", return_value=response) as request,
            patch("clearframe.stage3_gdelt_search.time.sleep") as sleep,
        ):
            with self.assertRaisesRegex(GDELTSearchError, "rate limiting persisted after 10 attempts"):
                search_gdelt("query", "20260911000000", "20260928000000")

        self.assertEqual(request.call_count, 10)
        self.assertEqual(sleep.call_count, 9)


if __name__ == "__main__":
    unittest.main()
