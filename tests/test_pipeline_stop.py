import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import run


class SingleActorStopTests(unittest.TestCase):
    def test_pipeline_stops_before_gdelt_when_only_one_actor_country_exists(self):
        plan = {
            "location": "South Africa",
            "source_country": "South Africa",
            "original_source_country": "United States",
            "actor_countries": ["South Africa"],
            "terms": ["mass shootings", "crime", "gang violence"],
            "article_type": "breaking_news",
            "window_days_before": 14,
            "window_days_after": 14,
        }

        with (
            patch.object(run, "OpenAI", return_value=object()),
            patch.object(run, "get_article_text", return_value=(
                "article text", datetime(2026, 9, 27, tzinfo=timezone.utc), "Source headline"
            )),
            patch.object(run, "make_query_plan", return_value=plan),
            patch.object(run, "search_gdelt_balanced") as search,
        ):
            result = run.run_clearframe_pipeline("https://source.example", api_key="test")

        search.assert_not_called()
        self.assertIn("only one", result["stop_reason"])
        self.assertEqual(result["plan"]["actor_countries"], ["South Africa"])
        self.assertEqual(result["source_title"], "Source headline")

    def test_pipeline_stops_before_gdelt_for_european_union_actor(self):
        plan = {
            "location": "Bern",
            "source_country": "Switzerland",
            "original_source_country": "United States",
            "actor_countries": [
                "Switzerland", "Russia", "Ukraine", "European Union"
            ],
            "terms": ["neutrality", "sanctions", "referendum"],
            "article_type": "breaking_news",
            "window_days_before": 14,
            "window_days_after": 14,
        }

        with (
            patch.object(run, "OpenAI", return_value=object()),
            patch.object(run, "get_article_text", return_value=(
                "article text", datetime(2026, 9, 25, tzinfo=timezone.utc), "Source headline"
            )),
            patch.object(run, "make_query_plan", return_value=plan),
            patch.object(run, "search_gdelt_balanced") as search,
        ):
            result = run.run_clearframe_pipeline("https://source.example", api_key="test")

        search.assert_not_called()
        self.assertIn("European Union", result["stop_reason"])
        self.assertIn("not a valid GDELT source country", result["stop_reason"])

    def test_pipeline_stops_without_fallback_after_gdelt_failure(self):
        plan = {
            "location": "Bern",
            "source_country": "Switzerland",
            "original_source_country": "United States",
            "actor_countries": ["Switzerland", "Russia"],
            "terms": ["neutrality", "sanctions", "referendum"],
            "article_type": "breaking_news",
            "window_days_before": 14,
            "window_days_after": 14,
        }

        with (
            patch.object(run, "OpenAI", return_value=object()),
            patch.object(run, "get_article_text", return_value=(
                "article text", datetime(2026, 9, 25, tzinfo=timezone.utc), "Source headline"
            )),
            patch.object(run, "make_query_plan", return_value=plan),
            patch.object(
                run,
                "search_gdelt_balanced",
                side_effect=run.GDELTSearchError("rate limiting persisted"),
            ) as search,
            patch.object(run, "search_gdelt_fallback") as fallback,
        ):
            result = run.run_clearframe_pipeline("https://source.example", api_key="test")

        search.assert_called_once()
        fallback.assert_not_called()
        self.assertIn("GDELT search failed", result["stop_reason"])
        self.assertIn("stopped without fallback", result["stop_reason"])


if __name__ == "__main__":
    unittest.main()
