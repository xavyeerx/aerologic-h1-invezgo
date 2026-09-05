import unittest
from unittest.mock import patch

from core.data_provider import fetch_stock_sector


class StockSectorTests(unittest.TestCase):
    def setUp(self):
        fetch_stock_sector.cache_clear()

    @patch("core.data_provider._request")
    def test_fetches_sector_from_stock_information(self, request):
        request.return_value = {"code": "BBYB", "sector": "Keuangan"}

        self.assertEqual(fetch_stock_sector("BBYB.JK"), "Keuangan")
        self.assertEqual(fetch_stock_sector("BBYB.JK"), "Keuangan")
        request.assert_called_once_with(
            "GET", "analysis/information/BBYB", category="stock_information"
        )

    @patch("core.data_provider._request", return_value={"code": "TEST"})
    def test_returns_unknown_when_sector_is_missing(self, request):
        self.assertEqual(fetch_stock_sector("TEST"), "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
