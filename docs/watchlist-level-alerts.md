# Watchlist Level Alerts V1 — implemented locally

No application database migration or deployment has run. Migration verification
uses isolated test databases only.

## Existing input evidence

The screenshot OCR pipeline preserves symbol, original OCR row note, confidence
and bounding box during extraction. The database preserves upload ID, a UTC
ingestion date, upload timestamps, a validated symbol-row ID, and original_note.
It does not extract the date printed on the image. Before this work it stored no
structured directions or numeric trigger levels. The existing private workflow
stages an upload for review and then activates the entire daily watchlist.

Multiple visual rows for a validated symbol now survive extraction, while the
scanner's symbol universe remains deduplicated. Structured level instructions
retain each matching row's exact note and bounding box. Existing original_note
remains available as context. No individual-alert creation workflow is introduced.

## Literal parsing implemented

Recognized numeric conditions: LONG above/over/> price, SHORT below/under/< price,
case insensitive, with an optional dollar sign and up to eight decimal places.
Repeated identical levels collapse; distinct numeric levels remain distinct.

The repository image fixture contains “long over 200, Short under 198”, “Long over
371”, and “Long over 72”; these are explicit conditions. Pivot columns alone,
“No Go”, PMH/PDL/MTF references, “Short the POPs vs 42”, “Gap & Go”, ranges,
thousands-separated prices, and implied-direction prose do not become triggers.
No substitutions or inferred strategy conditions are introduced. Original notes
are retained, not rewritten. OCR accuracy remains subject to upload review.

## Daily activation and persistence

Migration 0015 adds nullable trading_date to watchlist_uploads, structured instructions on watchlist_symbols, durable
watchlist_level_monitors, and a unique nullable level_key on the existing alerts
table. Database immutability protection includes these events while preserving
the existing FORMING condition. There is no historical alert backfill.

The canonical **trading_date is the America/New_York calendar date at successful
ingestion**, assigned once when a validated image import commits. It is not UTC
date, upload-start time, activation time, or a printed image date. Processing that
crosses local midnight belongs to the day when ingestion succeeds. New York DST
conversion is timezone-aware. The legacy date column remains UTC upload bookkeeping.

The durable key is trading_date + symbol + direction + canonical decimal level.
Existing whole-watchlist activation automatically arms **all** actionable levels
in that upload; no individual alert creation is required. Upload review remains
the existing OCR safety workflow. Activation atomically replaces the monitor set. Same-day
replacement keeps triggered identities; removed levels become inactive. Re-added
inactive levels seed a new price baseline but cannot create a second daily event.

Levels expire at New York midnight, even if the previous snapshot is still scanned
for context. They never carry into scanner-generated rollover snapshots. The
worker preserves a current New York upload across UTC midnight. A new trading day
requires a successfully ingested watchlist for that day; yesterday's upload cannot
be reactivated to re-arm levels. Legacy uploads with no recorded trading_date do
not receive invented historical dates or monitors; upload again to enable levels.
Monitor rows may remain physically marked active until replacement, but the date
predicate makes them ineligible after midnight. Historical events retain their
original trading_date and are never joined to mutable monitor metadata for display.

PriceObservingProvider captures the last available one-minute bar close from the
existing Alpaca/IEX fetch before strategy processing, returning the same candle
series unchanged. It makes no additional request. This is a polling observation,
not a tick-exact crossing time; evidence stores both fetch observation time and
the provider bar timestamp. Intermediate crossings between polls can be missed.

The event collector always uses America/New_York; callers cannot override the
trading-day timezone. Publication timestamps are normalized to UTC before comparison. First observation only seeds
the baseline, even if already beyond the trigger. LONG requires previous <= level
and current > level; SHORT requires previous >= level and current < level.
Future, previous-day, and out-of-order observations are rejected. A per-level
savepoint makes cursor/event updates atomic and isolates persistence failures.
The worker publishes captured prices independently of scan errors and FORMING
outputs. An indicator failure after a successful price fetch cannot suppress a
level event; a failed market-data fetch supplies no price and leaves its baseline
unchanged. The existing publication lock and snapshot check reject superseded
watchlists. There are no per-level network calls or notification operations.

Evidence includes date, symbol, direction, level, observed and previous prices,
their observation/bar timestamps, original note, source upload/row/bounding box,
and internal provider/feed/timeframe. Public DTOs expose only presentation fields,
including the authorized original note; identities/provenance remain private.
The web alert table distinguishes LEVEL TRIGGER LONG/SHORT from FORMING events.
The chart's existing FORMING markers remain FORMING-only.

## Limitations and unchanged behavior

This is sampled bar-close monitoring, not a real-time tick subscription. Price
changes between polls can be missed. The first observation already beyond a level
does not invent a crossing. A failed persistence attempt retains the last baseline
and retries against the next valid price; it cannot reconstruct a transient missed
crossing. Decimal prices support eight fractional digits, without rounding into a
different trigger. Ambiguous formats remain notes and require future explicit
parsing requirements. No printed-date OCR or ticker/price correction is attempted.

FORMING calculations and transition semantics remain unchanged, with strategy
identity `experimental-forming-v1/b067b3150de3`. Sector enrichment and Reliability V1
remain intact. No Discord, Backtest, trade execution, or new market-data provider.

## Local verification (2026-09-28)

The focused level suite passed 23 tests. Combined level, FORMING alert, reliability
and metadata checks ran 66 tests with one PostgreSQL-only skip on SQLite. The full
backend suite ran 203 tests: SQLite passed with two environment-specific skips;
disposable localhost PostgreSQL passed with only the unavailable Tesseract OCR
test skipped. Live HTTP transports were blocked in these backend runs. Public
frontend tests passed 11/11 and private frontend tests 10/10; both builds and
format checks passed, along with compileall and git diff --check. The disposable
PostgreSQL container was removed. No production or application database was used.


## Crash recovery verification (2026-10-02)

Inspection before editing found more completed work than the last-known crash
summary: parser and duplicate OCR row preservation, migration 0015, models,
durable monitors and immutable events, whole-watchlist activation wiring,
scanner price capture/publication, New York ingestion dates and expiry,
LEVEL TRIGGER presentation, and 23 focused tests all survived. The initial
backend run confirmed 201 passes and two skips (203 total). No implementation
was restarted and no competing migration was created.

The remaining recovery work was verification and enforcing the canonical timezone
at the collector boundary. Removed the alternate-timezone argument and normalized
publication timestamps; added checks for database uniqueness, offset timestamps,
unsuccessful ingestion, superseded publication, and concurrent PostgreSQL level
publication. Existing OCR review and whole-watchlist activation semantics remain:

1. Upload creates an image snapshot; processing extracts and validates symbol rows.
2. Successful validated ingestion persists structured instructions and assigns
   `trading_date` once from `processed_at` in America/New_York.
3. The synchronous private upload flow calls activation immediately. The staged
   Daily Watchlist flow keeps its existing review step and Activate action.
4. Whole-watchlist activation locks AppState and atomically activates every
   actionable level, deactivates removed levels, and replaces the active snapshot.
5. Each scanner cycle captures the existing provider's latest available one-minute
   close before strategy processing. Publication checks the active snapshot under
   the same AppState lock, then collects level events independently of FORMING.

Files edited during this recovery only:

- `backend/level_alerts.py`
- `tests/test_level_alerts.py`
- `docs/watchlist-level-alerts.md`

All pre-existing tracked and untracked changes were preserved. The recovered
working tree already contained changes in the following files:

```text
README.md
backend/alerts.py
backend/api.py
backend/database/models.py
backend/internal_api.py
backend/store.py
discovery/service.py
docker-compose.yml
docs/architecture.md
docs/discovery.md
docs/frontend.md
docs/security.md
frontend/src/App.jsx
frontend/src/Discovery.jsx
frontend/src/components.jsx
frontend/src/pages.jsx
frontend/tests/dashboard.spec.js
ripster_scanner/watchlist.py
scanner/worker.py
strategy-lab-frontend/src/DailyWatchlist.jsx
strategy-lab-frontend/tests/replay.spec.js
tests/test_api.py
tests/test_worker.py
backend/level_alerts.py
discovery/fmp.py
discovery/metadata.py
discovery/metadata_provider.py
docs/sector-enrichment.md
docs/watchlist-level-alerts.md
migrations/versions/0014_symbol_metadata_enrichment.py
migrations/versions/0015_watchlist_level_alerts.py
ripster_scanner/watchlist_levels.py
scanner/price_observation.py
tests/test_level_alerts.py
tests/test_metadata.py
tests/test_watchlist_levels_parser.py
tools/README.md
tools/fmp_metadata_poc.py
tools/test_fmp_metadata_poc.py
```

UI tests regenerated two previously clean documentation screenshots; those generated
changes were restored to their original contents. No pre-existing changes were
removed. No commit, Discord work, deployment, production access, or application
database migration occurred.

Recovery verification results:

| Check | Result |
| --- | --- |
| Full backend, disposable PostgreSQL | 207 passed, 1 skipped (208 total) |
| Full backend, SQLite before adding PostgreSQL-only concurrency test | 205 passed, 2 skipped (207 total) |
| Focused parser + level tests, PostgreSQL | 28 passed, including concurrent publication |
| Combined level + reliability + metadata + alert + FORMING, SQLite | 74 passed, 2 PostgreSQL-only skips (76 total) |
| Reliability V1 | 7 passed |
| Sector Enrichment V1 | 18 passed |
| FORMING Alert Foundation | 18 passed on PostgreSQL, including concurrency |
| FORMING calculations | 5 passed |
| Public frontend | 11 passed; build and formatting passed |
| Private frontend | 10 passed; build and formatting passed |
| Python compileall / git diff --check | Passed |

The PostgreSQL skip is the real Tesseract image-upload integration test, which
requires the application Docker image. All backend runs blocked live requests/httpx
HTTP transports. Migration 0015 remains the single additive revision after 0014;
full-suite migration checks exercise legacy preservation and repeat upgrades in
isolated databases. The test PostgreSQL container used temporary storage and was
removed after verification. No application or production database was accessed.
Public DTO allowlist and immutable-event tests passed. FORMING strategy identity,
calculations and transition semantics remain unchanged.
