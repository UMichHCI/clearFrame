import unittest
from unittest.mock import Mock, patch

from clearframe.stage3_gdelt_search import GDELTSearchError, search_gdelt


class GDELTSearchTests(unittest.TestCase):
    def test_persistent_rate_limit_raises_after_five_attempts(self):
        response = Mock(status_code=429, text="rate limited")

        with (
            patch("clearframe.stage3_gdelt_search.requests.get", return_value=response) as request,
            patch("clearframe.stage3_gdelt_search.time.sleep") as sleep,
        ):
            with self.assertRaisesRegex(GDELTSearchError, "rate limiting persisted"):
                search_gdelt("query", "20260911000000", "20260928000000")

        self.assertEqual(request.call_count, 5)
        self.assertEqual(sleep.call_count, 4)


if __name__ == "__main__":
    unittest.main()
