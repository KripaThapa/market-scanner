# Discovery Engine V1

Discovery answers which symbols enter the active scanning universe. It does not add an entry rule or change Experimental Forming Setup V1.

## Active universe — IMPLEMENTED

The polling worker uses this precedence, independently of the research window:

```text
Today's activated uploaded watchlist (America/New_York calendar date)
    ↓ only if missing
Previous applicable XNYS trading session's activated uploaded watchlist
    ↓ only if missing
No watchlist-derived stocks
```

Exactly one upload is selected. Among activated uploads for a date, the most recent
activation wins (`processed_at`, then ID). `queued` and `scanned` uploads qualify;
staged/unreviewed, failed, empty, config, and rollover snapshots do not. Canonical
`trading_date` comes from successful ingestion, not UTC upload bookkeeping or
printed image dates. Legacy uploads without that date are not assigned invented
historical dates. Upload and activate again to make them eligible.

Previous trading day uses the existing `USEquityMarketCalendar.adjacent(day,
'previous')`, backed by the exchange-calendars XNYS schedule. Monday selects Friday;
after a holiday it selects the prior exchange session. On weekends/holidays it
selects the last session strictly before today. There is no progressively older
search. Outside the bundled calendar range, previous-day fallback is unavailable;
a valid same-date activated upload and context symbols can still be scanned.

Historical uploaded watchlists remain stored and unchanged. They are not accumulated
into the active universe. A fallback creates a membership-only rollover snapshot,
reused through the same New York date. A new activated upload replaces that fallback
through the existing AppState compare-and-set/publication lock. A scan superseded
by an activation cannot publish its old universe. A scan crossing New York midnight
is discarded and re-selects on the next cycle. The old `SCANNER_JSON_FALLBACK`
worker option is retired; standalone CLI JSON input remains available.

## Always-monitored context — IMPLEMENTED

Every normal cycle includes `SPY`, `QQQ`, `MAGS`, `AAPL`, `MSFT`, `NVDA`, `AMZN`,
`META`, `GOOGL`, and `TSLA`, even without any watchlist or outside the discovery
window. MAGS supplements all seven individual stocks. `MARKET_CONTEXT` membership
is internal provenance, merged by normalized symbol with watchlist and enabled
automatic sources before scanning. Each symbol is scanned once per cycle. Context
symbols use the same provider abstraction, metadata enrichment, failure isolation,
and existing FORMING pipeline; no market-context classifications, rules, or gates
are introduced. Missing provider bars remain NO DATA under existing behavior.

**VIX is unavailable:** the current adapter issues `StockBarsRequest` minute-bar
requests with `DataFeed.IEX`; it has no spot-index endpoint. [Alpaca documents that
spot VIX/index-level data is not in its offering](https://docs.alpaca.markets/us/docs/index-options).
No guessed ticker, volatility ETF substitute, or new provider is used.
[Roundhill identifies MAGS as its U.S.-listed ETF](https://www.roundhillinvestments.com/etf/mags/).
MAGS uses the existing stock/ETF request path without a new adapter. Mocked SDK
transport tests cover SPY, QQQ and MAGS requests; live account/feed coverage was
not queried or guaranteed. IEX-only data can be sparse or absent for a given poll.

## Automatic discovery — retained, disabled by default

`AUTO_DISCOVERY_ENABLED=false` is the code, `.env.example`, and Compose default.
Only `true` or `false` is accepted (case insensitive). The old `DISCOVERY_ENABLED`
name is ignored. Local secret-bearing `.env` was not read or changed.

When disabled, Most Active, Top Gainers and Top Losers contribute no symbols,
including cached same-day memberships. No screener is constructed by the normal
worker and no automatic discovery requests are made. Missing watchlists never
implicitly enable discovery. Candle requests and optional sector metadata requests
still run for the selected stocks/context instruments.

Setting `AUTO_DISCOVERY_ENABLED=true` explicitly enables the retained Alpaca
Screener sources in addition to the selected upload and context instruments.
Existing interval/top-N settings remain `DISCOVERY_INTERVAL_SECONDS=300` and
`DISCOVERY_TOP_N=10`. Refresh requires the existing research window (default
08:00 inclusive–10:00 exclusive America/Chicago) and an XNYS session. Each source
refreshes independently. Failed sources retain same-day last-known membership;
successful empty responses remove membership. Outside the refresh window,
same-day cached automatic membership remains available when enabled. Context
instruments continue scanning on non-sessions; automatic discovery does not.
The screener implementation and historical memberships/events remain intact.

## Daily level alerts — unchanged

Previous-session watchlist symbols can be scanned as fallback, but their explicit
LONG/SHORT levels never carry over. Rollover snapshots contain membership only;
they do not copy notes or structured levels and do not re-arm yesterday's monitors.
Context membership alone creates no levels. A context symbol gets a level monitor
only from an explicit actionable instruction in today's activated upload.
Identity remains `trading_date + symbol + direction + canonical trigger_level`;
New York expiry, crossing semantics and immutable historical events are unchanged.

`discovery_memberships` holds current same-day membership and first/last seen timestamps. `discovery_events` preserves appearances, changes, and departures. `discovery_source_status` distinguishes OK, EMPTY, and FAILED. `research_observation_sources` records every source attached to each observation. These tables are internal research data. Public DTOs contain no source type or upload/image identity.

Sector Enrichment V1 resolves classification through a provider-neutral persistent `SymbolMetadataService` at the merged-universe boundary. FMP supplies reference metadata only; Alpaca/IEX supplies scanner candles. Known cache entries take precedence over optional `config/sectors.json` fallback, and UNKNOWN symbols still scan. Complete profiles use a 7-day TTL; failures/not-found/partial profiles use a 24-hour retry. See [cache, failure, precedence and history policy](sector-enrichment.md). `sector_snapshots` still stores only objective counts; no sector-strength rule is added.

Candle timestamps denote the start of a candle. For an evaluation time T, a 3m candle is COMPLETED when T is at or after start + 3 minutes, and PARTIAL before then; 10m follows the same rule with 10 minutes. Conversion is timezone-aware through America/New_York and UTC. The current detector can evaluate a partial 3m candle; such decisions remain eligible under existing behavior and are tagged PARTIAL. Old observations may have unknown/null metadata; history is not invented.

The normal Discovery page is a source-agnostic universe page. It shows symbol, sector, price, context, setup, candle state, and update time, with sector filtering and symbol navigation. Source filtering belongs only in future authenticated research tooling. There is no Finviz integration or website scraping. Future objective screens can be added through the provider-neutral discovery result model.

The private Strategy Lab **Daily Watchlist** workflow stages screenshot extraction for owner review, then activates the validated upload through the existing watchlist snapshot pointer. The upload is retained as a dated record. On the next normal scanner cycle, DiscoveryService merges the single selected upload's `UPLOADED_WATCHLIST` membership with context instruments and explicitly enabled Alpaca sources, deduplicates by symbol, and processes each member once. No frontend scan is started. Upload and provenance endpoints remain on the private internal API; the public API does not expose them.

The original UNKNOWN root cause was the absent optional mapping plus Alpaca models lacking sector/industry. FMP reference enrichment now supplies available classifications. The Dashboard's **Known sectors** still excludes UNKNOWN/Unclassified and separately counts missing data. No classifications are inferred from prices or company names.

## Configuration change file inventory

This universe-selection milestone changed only the following files; pre-existing
uncommitted work was preserved:

- `.env.example` (existing locally ignored example), `docker-compose.yml`
- `discovery/config.py`, `discovery/domain.py`, `discovery/service.py`
- `backend/store.py`, `scanner/worker.py`
- `tests/db_support.py`, `tests/test_scanner_universe.py` (new)
- `tests/test_worker.py`, `tests/test_discovery.py`, `tests/test_level_alerts.py`
- `tests/test_scanner_reliability.py`, `tests/test_metadata.py`, `tests/test_alerts.py`
- `README.md`, `docs/discovery.md`, `docs/architecture.md`

Existing worker regression fixtures now ingest/activate dated uploads and account
for the always-present context instruments. Alert/strategy expectations were not
weakened. No schema migration, strategy-version change, FORMING formula change,
Alert Foundation transition change, level crossing/deduplication change, new market
context rule, Discord implementation, Backtest/Research implementation change,
deployment, or production access is part of this milestone.

## Local verification (2026-10-02)

- Final full SQLite backend suite: 220 passed, 3 skipped (223 total).
- Final full disposable PostgreSQL backend suite: 222 passed, 1 skipped (223 total).
- Focused universe tests: 15 passed, covering configuration, cached-source exclusion,
  session fallback, replacement races, history retention, context deduplication,
  no implicit levels, and the existing ETF/IEX request path.
- Level-alert/parser regressions: 28 passed on PostgreSQL; fallback expiry explicitly
  verifies the previous-day symbol remains scanned without its level carrying over.
- FORMING Alert Foundation: 18 passed; FORMING calculations: 5 passed; calculation
  primitives: 4 passed. Reliability V1: 7 passed. Sector Enrichment: 18 passed.
  Existing discovery/candle-state checks: 10 passed. API checks: 25 passed, 1 skipped.
- Public frontend: 11 passed; private frontend: 10 passed. Both builds and format
  checks passed. Public frontend was rerun with one worker after a browser-context
  startup timeout in the first parallel run; the failing run never entered that
  test body. Python compileall and git diff --check passed.

SQLite skips the two PostgreSQL row-lock concurrency tests and real Tesseract
integration. PostgreSQL passes both concurrency tests and skips only real Tesseract
integration, which requires the application Docker image. Backend runs blocked
requests/httpx/urllib live HTTP transports; provider responses were mocked.
Only isolated test schemas were migrated. The disposable PostgreSQL container used
temporary storage and was stopped/removed after verification. No application
migration, deployment or production access occurred. Pre-existing working-tree
changes remain uncommitted and preserved.
