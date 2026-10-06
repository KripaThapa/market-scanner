# Local FMP metadata proof of concept

This disposable tool has no scanner, database, research, alert, or frontend integration.
FMP is evaluated only for classification; Alpaca/IEX remains the scanner market-data source.

Run from the repository root:

```sh
.venv/bin/python -B tools/fmp_metadata_poc.py
.venv/bin/python -B -m unittest discover -s tools -p 'test_fmp_metadata_poc.py'
```

Set `FMP_API_KEY` in the process environment or the gitignored local `.env`.
Never commit the key. The script loads it without printing it, makes at most ten
sequential requests, uses 5-second connect / 20-second read timeouts, disables
redirects, and does not retry. Authentication failure, throttling, or a connection
failure stops further requests. HTTP 404 remains an HTTP error; an empty successful
profile list means NOT_FOUND. Missing fields remain UNKNOWN, and partial records
are counted separately. Exit status is 0 for complete coverage, 1 otherwise, or 2
when no key is available. No results are saved automatically.

Endpoint: `https://financialmodelingprep.com/stable/profile?symbol=SYMBOL`.
See [FMP quickstart](https://site.financialmodelingprep.com/developer/docs/quickstart).
FMP also documents [bulk profiles](https://site.financialmodelingprep.com/developer/docs/stable/profile-bulk)
using `/stable/profile-bulk?part=0`; bulk entitlement and comma-separated symbol
support on the single-profile endpoint were not tested.

The local run returned HTTP 200 and complete company/sector/industry fields for
NVDA, AAPL, MSFT, JPM, WMT, XOM, CRWV, GRAL, AMZN, and UNH (10/10).
All ten included CIK, ISIN, CUSIP, exchange, exchangeFullName, and country.
Observed raw sectors: Consumer Cyclical, Consumer Defensive, Energy,
Financial Services, Healthcare, Technology. No taxonomy normalization was applied.

This supports further metadata evaluation, not production deployment. Broader
coverage, classification accuracy, identifier lifecycle, freshness, account limits,
and licensing/caching/public-display rights still need verification. A future
cache should retain source and retrieval time; changes must not rewrite historical
alert snapshots. No historical classification or effective-date guarantees were
established by this current-profile POC.
# Read-only Lookout audit

`inspect_lookout.py` inspects October 5 CBRS/MSFT watchlist, monitor and immutable alert evidence inside the existing authorized application environment. It starts an explicit PostgreSQL READ ONLY transaction and never migrates, activates or backfills data. It handles older schemas and prints only whitelisted records, never connection settings. The local Compose database inspection found version 0012 and no October 5 uploads; this does not establish production findings. See [validation status](../docs/watchlist-lookout-alerts.md#october-5-read-only-validation-status).
