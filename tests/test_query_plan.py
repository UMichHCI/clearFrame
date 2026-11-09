import unittest
import json
from datetime import datetime, timezone
from unittest.mock import patch

from clearframe.stage2_query_plan import build_gdelt_query, clean_plan, make_query_plan


class CoveragePeriodTests(unittest.TestCase):
    def plan(self, **overrides):
        return {
            "location": "Bern",
            "source_country": "Switzerland",
            "original_source_country": "United States",
            "actor_countries": ["Switzerland", "Russia"],
            "terms": ["neutrality", "sanctions"],
            "article_type": "economics_policy",
            "coverage_start_date": "2020-01-01",
            "coverage_end_date": "2020-01-03",
            "coverage_period_reason": "The article dates the decision and its aftermath.",
            **overrides,
        }

    def test_retains_estimated_dates_and_reason(self):
        plan = self.plan()
        cleaned = clean_plan(plan)
        for field in ("coverage_start_date", "coverage_end_date", "coverage_period_reason"):
            self.assertEqual(cleaned[field], plan[field])

    def test_incomplete_period_is_retried_with_validation_feedback(self):
        invalid = self.plan(coverage_end_date=None)
        valid = self.plan()
        with patch("clearframe.stage2_query_plan.api_chat",
                   side_effect=[json.dumps(invalid), json.dumps(valid)]) as chat:
            result = make_query_plan("article text", "https://example.com", object())
        self.assertEqual(result, valid)
        self.assertEqual(chat.call_count, 2)
        feedback = chat.call_args.kwargs["user"]
        self.assertIn("both coverage dates are required and must not be null", feedback)
        self.assertIn("Always estimate", feedback)

    def test_invalid_plan_retry_is_bounded(self):
        with patch("clearframe.stage2_query_plan.api_chat",
                   return_value=json.dumps(self.plan(coverage_end_date=None))) as chat:
            with self.assertRaisesRegex(ValueError, "invalid after 3 attempts"):
                make_query_plan("article text", "https://example.com", object())
        self.assertEqual(chat.call_count, 3)

    def test_both_null_dates_trigger_correction(self):
        invalid = self.plan(coverage_start_date=None, coverage_end_date=None)
        valid = self.plan(coverage_period_reason="Approximate timing estimated from the context.")
        with patch("clearframe.stage2_query_plan.api_chat",
                   side_effect=[json.dumps(invalid), json.dumps(valid)]) as chat:
            self.assertEqual(make_query_plan("article", "https://example.com", object()), valid)
        self.assertEqual(chat.call_count, 2)

    def test_rejects_invalid_periods(self):
        invalid = [
            {"coverage_start_date": "2020-1-1"},
            {"coverage_start_date": "2020-02-30"},
            {"coverage_start_date": "2020-01-04"},
            {"coverage_start_date": None},
            {"coverage_end_date": "9999-01-01"},
            {"coverage_period_reason": ""},
        ]
        for overrides in invalid:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                clean_plan(self.plan(**overrides))

    def test_both_null_dates_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "both coverage dates are required"):
            clean_plan(self.plan(coverage_start_date=None, coverage_end_date=None))

    def test_same_day_period_includes_entire_day(self):
        _, start, end = build_gdelt_query(
            ["sanctions"], ["Russia"], "2020-01-01", "2020-01-01"
        )
        self.assertEqual((start, end), ("20200101000000", "20200101235959"))

    def test_current_day_is_capped_at_now(self):
        now = datetime(2026, 10, 12, 10, 30, tzinfo=timezone.utc)
        with patch("clearframe.stage2_query_plan.datetime") as clock:
            clock.strptime = datetime.strptime
            clock.now.return_value = now
            _, start, end = build_gdelt_query(
                ["sanctions"], ["Russia"], "2026-10-11", "2026-10-12"
            )
        self.assertEqual((start, end), ("20261011000000", "20261012103000"))

    def test_query_uses_event_terms_without_requiring_announcement_location(self):
        plan = clean_plan(self.plan(
            location="Washington, D.C.",
            source_country="United States",
            actor_countries=["United States", "Russia", "Ukraine", "Iran"],
            terms=["Trump", "diesel", "sanctions", "fuel prices"],
        ))
        query, _, _ = build_gdelt_query(
            plan["terms"], plan["query_countries"],
            plan["coverage_start_date"], plan["coverage_end_date"],
        )
        self.assertNotIn("Washington", query)
        self.assertEqual(query, '(Trump OR diesel OR sanctions OR "fuel prices") AND '
                         '(sourcecountry:russia OR sourcecountry:ukraine OR sourcecountry:iran)')
        self.assertEqual(plan["location"], "Washington, D.C.")



if __name__ == "__main__":
    unittest.main()
