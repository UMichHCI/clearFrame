import json
import threading
import unittest
from unittest.mock import patch

from clearframe.prompts import CATEGORY_SYNTHESIS_GUIDES, CHOMSKY_CATEGORIES
from clearframe.stage9_synthesis import (
    _synthesize_one_category,
    synthesize_category_paragraphs,
    synthesize_overall_summary,
)


class CategorySynthesisTests(unittest.TestCase):
    def test_each_category_call_contains_only_its_own_guide_and_evidence(self):
        for category in CHOMSKY_CATEGORIES:
            with self.subTest(category=category), patch(
                "clearframe.stage9_synthesis.api_chat",
                return_value=json.dumps({"include": False}),
            ) as mocked:
                evidence = [{"category_answer": {"difference": f"Evidence for {category}"}}]
                _synthesize_one_category(category, evidence, "Source text", object())

                system = mocked.call_args.kwargs["system"]
                self.assertIn(CATEGORY_SYNTHESIS_GUIDES[category], system)
                for other in CHOMSKY_CATEGORIES:
                    if other != category:
                        self.assertNotIn(CATEGORY_SYNTHESIS_GUIDES[other], system)
                        self.assertNotIn(other, system)
                payload = json.loads(mocked.call_args.kwargs["user"])
                self.assertEqual(payload["category"], category)
                self.assertEqual(payload["meaningful_pair_extractions"], evidence)

    def test_synthesizes_eligible_categories_independently(self):
        meaningful_categories = {
            "worthy_unworthy_victims",
            "selective_criteria",
        }
        category_answers = {
            category: {
                "meaningful_difference": category in meaningful_categories,
                "difference": f"Difference for {category}",
            }
            for category in CHOMSKY_CATEGORIES
        }
        pair_analyses = [{
            "row_index": 1,
            "article_reference": {
                "title": "Comparison",
                "outlet": "example.test",
                "source_country": "Testland",
                "url": "https://example.test/story",
            },
            "category_answers": category_answers,
        }]

        category_calls = []
        call_lock = threading.Lock()

        def fake_api_chat(client, system, user, **kwargs):
            payload = json.loads(user)
            if "category" in payload:
                category = payload["category"]
                with call_lock:
                    category_calls.append(category)
                return json.dumps({
                    "include": True,
                    "doctrinal_claim": f"Claim for {category}",
                    "paragraph": f"Your article differs on {category}.",
                    "examples": ["A concrete example."],
                    "supporting_articles": [pair_analyses[0]["article_reference"]],
                    "exclusion_reason": "",
                })
            return json.dumps({
                "summary": "Overall conclusion.",
                "supporting_articles": [],
            })

        with patch("clearframe.stage9_synthesis.api_chat", side_effect=fake_api_chat) as mocked:
            result = synthesize_category_paragraphs(pair_analyses, "Source text", object())

        self.assertEqual(set(result["category_decisions"]), set(CHOMSKY_CATEGORIES))
        self.assertEqual(set(category_calls), meaningful_categories)
        self.assertEqual(set(result["categories"]), meaningful_categories)
        self.assertEqual(mocked.call_count, len(meaningful_categories) + 1)
        self.assertEqual(result["summary"], "Overall conclusion.")
        self.assertEqual(result["summary_supporting_articles"], [])
        for category in meaningful_categories:
            self.assertEqual(result["categories"][category]["supporting_articles"],
                             [pair_analyses[0]["article_reference"]])
        for category in meaningful_categories:
            self.assertTrue(result["category_decisions"][category]["include"])
        for category in set(CHOMSKY_CATEGORIES) - meaningful_categories:
            self.assertFalse(result["category_decisions"][category]["include"])

    def test_no_meaningful_evidence_makes_no_api_calls(self):
        pair_analyses = [{
            "category_answers": {
                category: {"meaningful_difference": False}
                for category in CHOMSKY_CATEGORIES
            }
        }]

        with patch("clearframe.stage9_synthesis.api_chat") as mocked:
            result = synthesize_category_paragraphs(pair_analyses, "Source text", object())

        mocked.assert_not_called()
        self.assertEqual(result["categories"], {})
        self.assertEqual(set(result["category_decisions"]), set(CHOMSKY_CATEGORIES))
        self.assertTrue(all(
            not decision["include"]
            for decision in result["category_decisions"].values()
        ))

    def test_narrative_receives_all_findings_and_returns_one_uncited_paragraph(self):
        source = {"title": "Your article", "url": "https://source.example", "role": "source"}
        oman = {"title": "Oman article", "url": "https://oman.example", "source_country": "Oman"}
        iran = {"title": "Iran article", "url": "https://iran.example", "source_country": "Iran"}
        israel = {"title": "Israel article", "url": "https://israel.example", "source_country": "Israel"}
        categories = {
            "responsibility": {"paragraph": "Different accounts of responsibility.", "supporting_articles": [oman, iran]},
            "consequences": {"paragraph": "Different accounts of regional costs.", "supporting_articles": [israel, oman]},
        }
        narrative = (
            "Your article presents pressure as a path to agreement. Other accounts raise "
            "different questions about what would make an agreement possible."
            "\n\nCoverage from Oman considers the risk of renewed fighting. Coverage from Iran "
            "presents ending attacks as a condition for progress. The article from Israel "
            "adds the concerns of neighboring countries."
            "\n\nTogether these perspectives broaden the question from how to secure a deal "
            "to what its costs and conditions might be."
        )
        with patch("clearframe.stage9_synthesis.api_chat", return_value=json.dumps({
            "summary": narrative,
            "supporting_articles": [{"url": "https://invented.example"}],
        })) as mocked:
            result = synthesize_overall_summary(categories, object(), source)

        payload = json.loads(mocked.call_args.kwargs["user"])
        self.assertEqual(payload["categories"], categories)
        self.assertEqual(payload["article_references"], [source, oman, iran, israel])
        self.assertEqual(result, {"summary": narrative.replace("\n\n", " "), "supporting_articles": []})

    def test_summary_removes_stray_citations_and_joins_paragraphs(self):
        comparison = {
            "outlet": "oman.example", "source_country": "Oman", "url": "https://oman.example"
        }
        categories = {"first": {"supporting_articles": [comparison]}}
        response = {"summary": "The source article asks about a deal. [1][99]\n\nThe article from oman.example asks about costs. [2]"}
        with patch("clearframe.stage9_synthesis.api_chat", return_value=json.dumps(response)):
            result = synthesize_overall_summary(categories, object())
        self.assertEqual(result, {
            "summary": "Your article asks about a deal. The article from Oman asks about costs.",
            "supporting_articles": [],
        })

    def test_empty_or_failed_summary_does_not_erase_category_findings(self):
        categories = {"first": {"paragraph": "A supported finding.", "supporting_articles": []}}
        for response in ({"summary": ""}, []):
            with self.subTest(response=response), patch(
                "clearframe.stage9_synthesis.api_chat", return_value=json.dumps(response)
            ):
                result = synthesize_overall_summary(categories, object())
            self.assertEqual(result, {"summary": "", "supporting_articles": []})
        with patch("clearframe.stage9_synthesis.api_chat", side_effect=RuntimeError("Unavailable")):
            self.assertEqual(synthesize_overall_summary(categories, object()),
                             {"summary": "", "supporting_articles": []})
        self.assertEqual(categories["first"]["paragraph"], "A supported finding.")


if __name__ == "__main__":
    unittest.main()
