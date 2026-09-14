import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.data_provider import InvezgoError, _request


class DataProviderQuotaTests(unittest.TestCase):
    @patch("core.data_provider._auth_header", return_value={})
    @patch("core.data_provider._pace")
    @patch("core.data_provider._bump_quota")
    @patch("core.data_provider._get_client")
    def test_only_successful_2xx_response_is_counted(self, get_client, bump, _pace, _auth):
        response = SimpleNamespace(status_code=200, text='{"ok":true}', json=lambda: {"ok": True})
        get_client.return_value.request.return_value = response

        self.assertEqual(_request("GET", "test", category="chart"), {"ok": True})
        bump.assert_called_once_with("chart")

    @patch("core.data_provider._auth_header", return_value={})
    @patch("core.data_provider._pace")
    @patch("core.data_provider._bump_quota")
    @patch("core.data_provider._get_client")
    def test_http_error_is_not_counted(self, get_client, bump, _pace, _auth):
        response = SimpleNamespace(status_code=400, text="bad request")
        get_client.return_value.request.return_value = response

        with self.assertRaises(InvezgoError):
            _request("GET", "test", category="chart")
        bump.assert_not_called()


if __name__ == "__main__":
    unittest.main()
