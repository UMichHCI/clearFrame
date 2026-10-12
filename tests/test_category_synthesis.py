import json
import threading
import unittest
from unittest.mock import patch

from clearframe.prompts import CHOMSKY_CATEGORIES
from clearframe.stage9_synthesis import synthesize_category_paragraphs, synthesize_overall_summary


class CategorySynthesisTests(unittest.TestCase):
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
                "summary": "Overall conclusion. [1]",
                "supporting_articles": [],
            })

        with patch("clearframe.stage9_synthesis.api_chat", side_effect=fake_api_chat) as mocked:
            result = synthesize_category_paragraphs(pair_analyses, "Source text", object())

        self.assertEqual(set(result["category_decisions"]), set(CHOMSKY_CATEGORIES))
        self.assertEqual(set(category_calls), meaningful_categories)
        self.assertEqual(set(result["categories"]), meaningful_categories)
        self.assertEqual(mocked.call_count, len(meaningful_categories) + 1)
        self.assertEqual(result["summary"], "Overall conclusion. [1]")
        self.assertEqual(result["summary_supporting_articles"][0]["url"],
                         pair_analyses[0]["article_reference"]["url"])
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

    def test_summary_resolves_citations_to_supplied_articles(self):
        source = {"title": "Your article", "url": "https://source.example", "role": "source"}
        comparison = {"title": "Comparison", "url": "https://comparison.example", "source_country": "Oman"}
        unused = {"title": "Unused", "url": "https://unused.example"}
        categories = {
            "first": {"supporting_articles": [comparison, unused]},
            "second": {"supporting_articles": [comparison]},
        }
        response = json.dumps({
            "summary": "Your article leaves the costs unexamined. [1] Coverage from Oman names those costs. [2]",
            "supporting_articles": [{"url": "https://invented.example"}],
        })
        with patch("clearframe.stage9_synthesis.api_chat", return_value=response) as mocked:
            result = synthesize_overall_summary(categories, object(), source)

        payload = json.loads(mocked.call_args.kwargs["user"])
        self.assertEqual(len(payload["article_references"]), 3)
        self.assertEqual([a["url"] for a in result["supporting_articles"]],
                         [source["url"], comparison["url"]])
        self.assertEqual([a["citation_id"] for a in result["supporting_articles"]], [1, 2])

    def test_summary_rejects_missing_unknown_or_one_sided_citations(self):
        source = {"title": "Your article", "url": "https://source.example", "role": "source"}
        categories = {"first": {"supporting_articles": [{"url": "https://comparison.example"}]}}
        for summary in ("Uncited conclusion.", "Invented citation. [1][99]",
                        "Only source. [1]", "Only comparison. [2]"):
            with self.subTest(summary=summary), patch(
                "clearframe.stage9_synthesis.api_chat",
                return_value=json.dumps({"summary": summary}),
            ):
                result = synthesize_overall_summary(categories, object(), source)
            self.assertEqual(result, {"summary": "", "supporting_articles": []})


if __name__ == "__main__":
    unittest.main()
