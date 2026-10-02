"""Disposable classification-only POC; no application or database imports.

Run: .venv/bin/python -B tools/fmp_metadata_poc.py
Reads FMP_API_KEY from the environment or the repository's local .env.
Docs: https://site.financialmodelingprep.com/developer/docs/quickstart
"""

import json
import os
from collections import Counter
from pathlib import Path

import requests
from dotenv import dotenv_values

ENDPOINT = "https://financialmodelingprep.com/stable/profile"
SYMBOLS = ("NVDA", "AAPL", "MSFT", "JPM", "WMT", "XOM", "CRWV", "GRAL", "AMZN", "UNH")
FIELDS = ("symbol", "companyName", "sector", "industry", "cik", "isin", "cusip", "exchange", "exchangeFullName", "country")


def clean(value, key):
    """Keep provider text printable, bounded, and free of reflected credentials."""
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.replace(key, "[REDACTED]") if key else value
    return "".join(c if c.isprintable() and c != "|" else " " for c in value).strip()[:200] or None


def classify(symbol, payload, key):
    result = {"symbol": symbol, "status": "MALFORMED_RESPONSE"}
    if not isinstance(payload, list):
        return result
    if not payload:
        return {"symbol": symbol, "status": "NOT_FOUND"}
    if len(payload) != 1 or not isinstance(payload[0], dict):
        return result
    profile = payload[0]
    if profile.get("symbol") != symbol:
        return result
    values = {field: clean(profile.get(field), key) for field in FIELDS}
    # Preserve actual labels; placeholder strings are not usable classifications.
    for field in ("sector", "industry"):
        if (values[field] or "").casefold() in ("unknown", "n/a", "none", "null", "-"):
            values[field] = None
    complete = all(values[field] for field in ("companyName", "sector", "industry"))
    return {**values, "status": "OK" if complete else "PARTIAL",
            "present_fields": [field for field in FIELDS if field in profile],
            "usable_fields": [field for field in FIELDS if values[field] is not None]}


def fetch(session, symbol, key):
    try:
        with session.get(ENDPOINT, params={"symbol": symbol, "apikey": key},
                         timeout=(5, 20), allow_redirects=False) as response:
            status = response.status_code
            if status != 200:
                return {"symbol": symbol, "status": f"HTTP_{status}"}
            try:
                payload = response.json()
            except ValueError:
                return {"symbol": symbol, "status": "MALFORMED_RESPONSE", "http_status": status}
            return {**classify(symbol, payload, key), "http_status": status}
    except requests.Timeout:
        return {"symbol": symbol, "status": "TIMEOUT"}
    except requests.RequestException:
        # Never print exceptions: requests exceptions can include authenticated URLs.
        return {"symbol": symbol, "status": "REQUEST_FAILED"}


def main():
    key = os.environ.get("FMP_API_KEY", "").strip()
    if not key:
        key = (dotenv_values(Path(__file__).resolve().parents[1] / ".env",
                             interpolate=False).get("FMP_API_KEY") or "").strip()
    if not key:
        print("FMP_API_KEY is missing; no requests made.")
        return 2
    rows = []
    calls = 0
    with requests.Session() as session:
        for symbol in SYMBOLS:
            row = fetch(session, symbol, key)
            rows.append(row)
            calls += 1
            if row["status"] in {"HTTP_401", "HTTP_429", "REQUEST_FAILED"}:
                rows.extend({"symbol": remaining, "status": "NOT_REQUESTED"}
                            for remaining in SYMBOLS[calls:])
                break
    print("SYMBOL | COMPANY | SECTOR | INDUSTRY | STATUS")
    for row in rows:
        print(" | ".join(row.get(field) or "UNKNOWN" for field in
                         ("symbol", "companyName", "sector", "industry", "status")))
    counts = Counter(row["status"] for row in rows)
    print(json.dumps({"total_symbols": len(SYMBOLS), "http_calls": calls,
                      "successful_classifications": counts["OK"],
                      "partial_classifications": counts["PARTIAL"],
                      "not_found": counts["NOT_FOUND"],
                      "not_requested": counts["NOT_REQUESTED"],
                      "failed_requests": calls - counts["OK"] - counts["PARTIAL"] - counts["NOT_FOUND"],
                      "coverage_percent": 100 * counts["OK"] / len(SYMBOLS)}, indent=2))
    for field in ("sector", "industry"):
        print(f"Distinct raw {field}: " + json.dumps(sorted({row[field] for row in rows if row.get(field)})))
    print("Selected metadata only: " + json.dumps(rows, indent=2))
    return 0 if counts["OK"] == len(SYMBOLS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
