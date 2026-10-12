import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import run


class SingleActorStopTests(unittest.TestCase):
    def test_invalid_query_plan_stops_cleanly_before_search(self):
        with (
            patch.object(run, "OpenAI", return_value=object()),
            patch.object(run, "get_article_text", return_value=("article text", None, "Headline")),
            patch.object(run, "make_query_plan", side_effect=ValueError("invalid after 3 attempts")),
            patch.object(run, "search_gdelt_balanced") as search,
        ):
            result = run.run_clearframe_pipeline("https://example.com", api_key="test")
        search.assert_not_called()
        self.assertIn("could not build a valid query plan", result["stop_reason"])
        self.assertEqual(result["source_title"], "Headline")

    def test_pipeline_stops_before_gdelt_when_only_one_actor_country_exists(self):
        plan = {
            "location": "South Africa",
            "source_country": "South Africa",
            "original_source_country": "United States",
            "actor_countries": ["South Africa"],
            "terms": ["mass shootings", "crime", "gang violence"],
            "article_type": "breaking_news",
            "coverage_start_date": "2026-09-20",
            "coverage_end_date": "2026-09-24",
            "coverage_period_reason": "The incident and aftermath span September 20-24.",
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
            "coverage_start_date": "2026-09-20",
            "coverage_end_date": "2026-09-24",
            "coverage_period_reason": "The incident and aftermath span September 20-24.",
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

    def test_pipeline_stops_after_gdelt_failure(self):
        plan = {
            "location": "Bern",
            "source_country": "Switzerland",
            "original_source_country": "United States",
            "actor_countries": ["Switzerland", "Russia"],
            "terms": ["neutrality", "sanctions", "referendum"],
            "article_type": "breaking_news",
            "coverage_start_date": "2026-09-20",
            "coverage_end_date": "2026-09-24",
            "coverage_period_reason": "The incident and aftermath span September 20-24.",
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
        ):
            result = run.run_clearframe_pipeline("https://source.example", api_key="test")

        search.assert_called_once()
        self.assertEqual(search.call_args.kwargs["startdatetime"], "20260920000000")
        self.assertEqual(search.call_args.kwargs["enddatetime"], "20260924235959")
        self.assertIn("GDELT search failed", result["stop_reason"])
        self.assertIn("ClearFrame stopped", result["stop_reason"])

    def test_pipeline_rejects_null_dates_before_search(self):
        plan = {
            "location": "Bern",
            "source_country": "Switzerland",
            "original_source_country": "United States",
            "actor_countries": ["Switzerland", "Russia"],
            "terms": ["neutrality", "sanctions"],
            "article_type": "economics_policy",
            "coverage_start_date": None,
            "coverage_end_date": None,
            "coverage_period_reason": "No event dates or temporal cues are supplied.",
        }
        with (
            patch.object(run, "OpenAI", return_value=object()),
            patch.object(run, "get_article_text", return_value=(
                "article text", datetime(2026, 9, 25, tzinfo=timezone.utc), "Headline"
            )),
            patch.object(run, "make_query_plan", return_value=plan),
            patch.object(run, "search_gdelt_balanced") as search,
        ):
            result = run.run_clearframe_pipeline("https://source.example", api_key="test")

        search.assert_not_called()
        self.assertIn("both coverage dates are required", result["stop_reason"])

    def test_empty_search_stops_before_comparison_fetch(self):
        plan = {
            "location": "Washington, D.C.",
            "source_country": "United States",
            "original_source_country": "United States",
            "actor_countries": ["United States", "Russia", "Ukraine", "Iran"],
            "terms": ["diesel", "sanctions", "energy", "fuel prices"],
            "article_type": "breaking_news",
            "coverage_start_date": "2026-10-09",
            "coverage_end_date": "2026-10-10",
            "coverage_period_reason": "Announcement and immediate responses.",
        }
        with (
            patch.object(run, "OpenAI", return_value=object()),
            patch.object(run, "get_article_text", return_value=(
                "article text", datetime(2026, 10, 9, tzinfo=timezone.utc), "Headline"
            )),
            patch.object(run, "make_query_plan", return_value=plan),
            patch.object(run, "search_gdelt_balanced", return_value=[]) as search,
            patch.object(run, "fetch_candidate_texts") as fetch,
        ):
            result = run.run_clearframe_pipeline("https://source.example", api_key="test")

        search.assert_called_once()
        fetch.assert_not_called()
        self.assertIn("No GDELT candidates", result["stop_reason"])
        self.assertEqual(result["article_type"], "breaking_news")


if __name__ == "__main__":
    unittest.main()
