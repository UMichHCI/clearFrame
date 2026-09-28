import unittest

import pandas as pd

from clearframe.diversity import (
    deduplicate_candidate_metadata,
    remove_near_duplicate_texts,
    select_diverse_articles,
)


class DiversityTests(unittest.TestCase):
    def test_metadata_deduplication_is_country_aware(self):
        candidates = pd.DataFrame([
            {"url": "u1", "title": "Same Headline!", "sourcecountry": "X", "domain": "a.com"},
            {"url": "u2", "title": "same headline", "sourcecountry": "X", "domain": "b.com"},
            {"url": "u1", "title": "Different", "sourcecountry": "X", "domain": "c.com"},
            {"url": "u3", "title": "Same Headline", "sourcecountry": "Y", "domain": "d.com"},
        ])

        result = deduplicate_candidate_metadata(candidates)

        self.assertEqual(len(result), 2)
        self.assertEqual(set(result["url"]), {"u1", "u3"})

    def test_near_duplicate_text_keeps_longest_representative(self):
        base = " ".join(f"word{i}" for i in range(80))
        candidates = pd.DataFrame([
            {"row_index": 0, "title": "One", "sourcecountry": "X",
             "domain": "a.com", "article_text": base},
            {"row_index": 1, "title": "One update", "sourcecountry": "X",
             "domain": "b.com", "article_text": base + " additional reporting"},
            {"row_index": 2, "title": "Different", "sourcecountry": "X",
             "domain": "c.com", "article_text": " ".join(f"other{i}" for i in range(80))},
        ])

        result, clusters = remove_near_duplicate_texts(candidates)

        self.assertEqual(set(result["row_index"]), {1, 2})
        self.assertEqual(clusters[0]["kept_row_index"], 1)
        self.assertEqual(clusters[0]["removed_row_indices"], [0])

    def test_selection_prefers_outlet_breadth_and_caps_each_outlet(self):
        candidates = pd.DataFrame([
            {"row_index": index, "sourcecountry": "X", "domain": domain}
            for index, domain in enumerate([
                "a.com", "a.com", "a.com", "b.com", "b.com", "c.com"
            ])
        ])

        result = select_diverse_articles(candidates, max_per_country=10, max_per_outlet=2)

        self.assertEqual(list(result["domain"][:3]), ["a.com", "b.com", "c.com"])
        self.assertEqual(len(result), 5)
        self.assertLessEqual(result["domain"].value_counts().max(), 2)


if __name__ == "__main__":
    unittest.main()
