"""Offline checks for the disposable POC; no credentials or network needed."""

import unittest
from unittest.mock import Mock

import requests

from fmp_metadata_poc import classify, fetch


class MetadataPOCTests(unittest.TestCase):
    def test_complete_raw_labels_and_allowlist(self):
        row = classify("TEST", [{"symbol": "TEST", "companyName": "Example",
                                "sector": "Consumer Cyclical", "industry": "Specialty Retail",
                                "cik": "000001", "unnecessary": "private"}], "dummy-key")
        self.assertEqual(row["status"], "OK")
        self.assertEqual(row["sector"], "Consumer Cyclical")
        self.assertNotIn("unnecessary", row)

    def test_missing_classifications(self):
        for sector, industry in ((None, "Industry"), ("Sector", None), ("", "UNKNOWN")):
            with self.subTest(sector=sector, industry=industry):
                row = classify("TEST", [{"symbol": "TEST", "sector": sector,
                                         "industry": industry}], "dummy-key")
                self.assertEqual(row["status"], "PARTIAL")

    def test_not_found(self):
        self.assertEqual(classify("TEST", [], "dummy-key")["status"], "NOT_FOUND")

    def test_malformed_and_wrong_symbol(self):
        for payload in (None, {}, [None], [{"symbol": "OTHER"}], [{}, {}]):
            self.assertEqual(classify("TEST", payload, "dummy-key")["status"], "MALFORMED_RESPONSE")

    def test_reflected_key_and_control_characters(self):
        row = classify("TEST", [{"symbol": "TEST", "companyName": "dummy-key\n|\x1b"}], "dummy-key")
        self.assertNotIn("dummy-key", str(row))
        self.assertNotIn("\x1b", str(row))

    def test_network_failures_do_not_expose_exception(self):
        for error, expected in ((requests.Timeout("secret-url"), "TIMEOUT"),
                                (requests.ConnectionError("secret-url"), "REQUEST_FAILED")):
            session = Mock()
            session.get.side_effect = error
            row = fetch(session, "TEST", "dummy-key")
            self.assertEqual(row["status"], expected)
            self.assertNotIn("secret-url", str(row))
            self.assertEqual(session.get.call_args.kwargs["timeout"], (5, 20))
            self.assertFalse(session.get.call_args.kwargs["allow_redirects"])

    def test_http_errors_and_invalid_json(self):
        for status in (301, 401, 403, 404, 429, 500, 200):
            session = Mock()
            response = Mock(status_code=status)
            response.json.side_effect = ValueError("secret-response")
            session.get.return_value.__enter__ = Mock(return_value=response)
            session.get.return_value.__exit__ = Mock(return_value=False)
            row = fetch(session, "TEST", "dummy-key")
            self.assertEqual(row["status"], "MALFORMED_RESPONSE" if status == 200 else f"HTTP_{status}")
            self.assertNotIn("secret-response", str(row))


if __name__ == "__main__":
    unittest.main()
