import unittest
from unittest.mock import patch

from core.data_provider import fetch_stock_disclosures, fetch_stock_news


class StockNewsProviderTests(unittest.TestCase):
    @patch("core.data_provider._request")
    def test_fetch_stock_news_normalizes_code_and_extracts_rows(self, request):
        request.return_value = {"data": [{"id": "news-1"}]}

        rows = fetch_stock_news("mdia.JK")

        self.assertEqual(rows, [{"id": "news-1"}])
        request.assert_called_once_with(
            "GET",
            "posts/space/category/MDIA/NEWS",
            category="stock_news",
            params={"page": 1, "limit": 10},
        )

    @patch("core.data_provider._request")
    def test_fetch_stock_disclosures_normalizes_code_and_extracts_rows(self, request):
        request.return_value = {"data": [{"id": "report-1"}]}

        rows = fetch_stock_disclosures("mdia.JK")

        self.assertEqual(rows, [{"id": "report-1"}])
        request.assert_called_once_with(
            "GET",
            "posts/space/category/MDIA/REPORT",
            category="stock_disclosure",
            params={"page": 1, "limit": 10},
        )


if __name__ == "__main__":
    unittest.main()
