import unittest

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


if __name__ == "__main__":
    unittest.main()
