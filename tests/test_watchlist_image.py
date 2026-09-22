import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError

from ripster_scanner import app
from ripster_scanner.config import Config, load_config
from ripster_scanner.market_data import fetch_active_symbols
from ripster_scanner.watchlist import (extract_watchlist_rows, normalize_ticker,
                                       validate_candidates, validate_watchlist_rows)
from ripster_scanner.watchlist_image import OCRToken, WatchlistImageError, extract_image_tokens


class CandidateTests(unittest.TestCase):
    @staticmethod
    def token(text, left, top, confidence=99, width=None, height=24):
        return OCRToken(text, confidence, left, top, width or max(20, len(text) * 18), height)

    def test_row_geometry_rejects_prose_that_is_an_asset(self):
        tokens = [
            self.token("NVDA", 110, 100), self.token("RTX 60 GPUs reported", 280, 100, width=250),
            self.token("GO", 1900, 100), self.token("RUN", 2100, 130),
            self.token("NVDA", 110, 180), self.token("Second original note", 280, 180, width=250),
            self.token("UP", 1900, 180), self.token("BE", 2100, 210),
        ]
        rows = extract_watchlist_rows(tokens)
        self.assertEqual([row.symbol for row in rows], ["NVDA", "NVDA"])
        self.assertIn("Second original note", rows[1].original_note)
        imported = validate_watchlist_rows(rows, {"NVDA", "GO", "RUN", "UP", "BE"})
        self.assertEqual(imported.validated, ("NVDA",))

    def test_rows_support_stacked_symbols_and_preserve_note(self):
        tokens = [
            self.token("SPY", 110, 100), self.token("QQQ", 110, 125),
            self.token("Market note", 280, 108, width=180),
            self.token("Game plan", 1900, 108, width=180),
        ]
        rows = extract_watchlist_rows(tokens)
        self.assertEqual([row.symbol for row in rows], ["SPY", "QQQ"])
        self.assertEqual(rows[0].original_note, rows[1].original_note)

    def test_normalization(self):
        for raw, expected in [(" $nvda, ", "NVDA"), ("(amd)", "AMD"),
                              ("•TSLA!", "TSLA"), ("BRK.B", "BRK.B"),
                              ("NVD4", "NVD4"), ("NV DA", "NV DA")]:
            with self.subTest(raw=raw):
                self.assertEqual(normalize_ticker(raw), expected)

    def test_deduplication_and_validation(self):
        tokens = [OCRToken("nvda,", 40), OCRToken("AMD", 99),
                  OCRToken("$NVDA", 98), OCRToken("MFTA", 99), OCRToken("TSLA", 30)]
        result = validate_candidates(tokens, {"NVDA", "AMD", "TSLA"})
        self.assertEqual(result.candidates, ("NVDA", "AMD", "MFTA", "TSLA"))
        self.assertEqual(result.validated, ("NVDA", "AMD"))
        self.assertEqual([r.candidate for r in result.rejected], ["MFTA", "TSLA"])
        self.assertIn("confidence", result.rejected[-1].reason)

    def test_noise_is_rejected_even_if_also_an_asset(self):
        noise = ["RIPSTER", "WATCHLIST", "LONG", "SHORT", "ON", "IT", "A+", "EMA",
                 "VWAP", "$123.45", "10M", "NVD4", "NV/DA", "!!!"]
        result = validate_candidates([OCRToken(word, 99) for word in noise], set(noise))
        self.assertEqual(result.validated, ())
        self.assertEqual(len(result.rejected), len(noise))

    def test_nan_confidence_never_accepted(self):
        result = validate_candidates([OCRToken("NVDA", float("nan"))], {"NVDA"})
        self.assertFalse(result.validated)


class OCRTests(unittest.TestCase):
    def test_missing_image_does_not_invoke_ocr(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "ripster_scanner.watchlist_image.subprocess.run"
        ) as run:
            with self.assertRaisesRegex(WatchlistImageError, "does not exist"):
                extract_image_tokens(Path(directory) / "missing.png")
            run.assert_not_called()

    @patch("ripster_scanner.watchlist_image.subprocess.run")
    def test_tesseract_tsv_adapter_and_path_with_spaces(self, run):
        run.return_value.stdout = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
                                   "1\t1\t0\t0\t0\t0\t0\t0\t0\t0\t-1\t\n"
                                   "5\t1\t2\t3\t4\t5\t10\t20\t50\t24\t96.3\tNVDA\n"
                                   "5\t1\t2\t3\t4\t6\t80\t20\t50\t24\t50\tMFTA\n")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "watch list.png"
            path.touch()
            self.assertEqual(extract_image_tokens(path),
                             [OCRToken("NVDA", 96.3, 10, 20, 50, 24, 2, 3, 4, 5),
                              OCRToken("MFTA", 50, 80, 20, 50, 24, 2, 3, 4, 6)])
            self.assertEqual(run.call_args.args[0][1], str(path.resolve()))
            self.assertEqual(run.call_args.kwargs["timeout"], 60)

    @patch("ripster_scanner.watchlist_image.subprocess.run")
    def test_ocr_failures_are_actionable(self, run):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "image.png"
            path.touch()
            for error in [FileNotFoundError(), subprocess.TimeoutExpired("tesseract", 60),
                          subprocess.CalledProcessError(1, "tesseract")]:
                with self.subTest(error=error):
                    run.side_effect = error
                    with self.assertRaises(WatchlistImageError):
                        extract_image_tokens(path)
            run.side_effect = None
            run.return_value.stdout = "invalid output"
            with self.assertRaisesRegex(WatchlistImageError, "invalid TSV"):
                extract_image_tokens(path)


class AssetTests(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_validation_directory_is_read_only_and_filters_inactive_assets(self, urlopen):
        import json
        response = io.StringIO(json.dumps([
            {"symbol": "NVDA", "status": "active", "class": "us_equity"},
            {"symbol": "OLD", "status": "inactive", "class": "us_equity"},
            {"symbol": "BTC/USD", "status": "active", "class": "crypto"},
        ]))
        urlopen.return_value.__enter__.return_value = response
        self.assertEqual(fetch_active_symbols("fake", "fake"), {"NVDA"})
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertIn("/v2/assets?", request.full_url)
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 30)

    @patch("urllib.request.urlopen", side_effect=URLError("offline"))
    def test_directory_failure_does_not_approve_symbols(self, urlopen):
        with self.assertRaisesRegex(ValueError, "No screenshot symbols will be scanned"):
            fetch_active_symbols("fake", "fake")


class InputSelectionTests(unittest.TestCase):
    @patch.dict(os.environ, {"ALPACA_API_KEY": "fake", "ALPACA_SECRET_KEY": "fake"})
    @patch("ripster_scanner.config.load_dotenv")
    def test_config_file_fallback_and_image_override(self, dotenv):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "watchlist.json"
            path.write_text('["AMD", "NVDA"]')
            self.assertEqual(load_config(path).symbols, ("AMD", "NVDA"))
            self.assertEqual(load_config(Path(directory) / "missing.json", symbols=()).symbols, ())

    @patch("ripster_scanner.app.print_watchlist_summary")
    @patch("ripster_scanner.app.scan_watchlist", return_value=[])
    @patch("ripster_scanner.app.StockHistoricalDataClient")
    @patch("ripster_scanner.app.load_config", return_value=Config("fake", "fake", ("AMD",)))
    @patch("ripster_scanner.app.extract_image_tokens")
    def test_cli_without_image_uses_existing_config(self, extract, config, client, scan, display):
        app.main([])
        extract.assert_not_called()
        config.assert_called_once_with()
        self.assertEqual(scan.call_args.args[0].symbols, ("AMD",))

    @patch("ripster_scanner.app.print_watchlist_summary")
    @patch("ripster_scanner.app.scan_watchlist", return_value=[])
    @patch("ripster_scanner.app.StockHistoricalDataClient")
    @patch("ripster_scanner.app.asset_directory_uses_paper", return_value=True)
    @patch("ripster_scanner.app.fetch_active_symbols", return_value={"NVDA", "AMD"})
    @patch("ripster_scanner.app.load_config", return_value=Config("fake", "fake", ()))
    @patch("ripster_scanner.app.extract_image_tokens", return_value=[
        OCRToken("NVDA", 99), OCRToken("MFTA", 99), OCRToken("AMD", 99)])
    def test_cli_passes_only_validated_symbols_to_scanner(self, extract, config, assets,
                                                         paper, client, scan, display):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            app.main(["--watchlist-image", "input/watchlist.png"])
        config.assert_called_once_with(symbols=())
        self.assertEqual(scan.call_args.args[0].symbols, ("NVDA", "AMD"))
        self.assertIn("2 valid symbols loaded", output.getvalue())
        self.assertIn("MFTA: not found", output.getvalue())
        extract.return_value = []
        scan.reset_mock()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                app.main(["--watchlist-image", "input/watchlist.png"])
        self.assertEqual(error.exception.code, 2)
        scan.assert_not_called()

    @patch("ripster_scanner.app.scan_watchlist")
    def test_missing_image_cli_fails_cleanly_without_fallback(self, scan):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stderr(io.StringIO()) as err:
            with self.assertRaises(SystemExit) as error:
                app.main(["--watchlist-image", str(Path(directory) / "missing.png")])
            self.assertEqual(error.exception.code, 2)
            self.assertIn("does not exist", err.getvalue())
            self.assertNotIn("Traceback", err.getvalue())
            scan.assert_not_called()


if __name__ == "__main__":
    unittest.main()
