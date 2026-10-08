# Watchlist Lookout Alerts V2

**IMPLEMENTED in application code; not deployed.** A Watchlist Lookout Alert is an attention notification, not a trade recommendation. LONG LOOKOUT and SHORT LOOKOUT preserve literal price instructions; neither means BUY or SELL.

```text
uploaded watchlist → structured levels + original Game Plan
                   → existing daily level monitors
                   → immutable persisted lookout alert
                   → web UI + optional browser sound
```

## Extraction and review

The October 6 structured-column regression is fixed separately in [table extraction](watchlist-table-extraction.md), including measured OCR root cause, corroborated heading/border detection, wrapped rows, Blank versus Unavailable review fields and development diagnostics. This extraction-only change requires no migration beyond deployed 0016 and does not change lookout triggers.

The staged upload → process → review → activate workflow is retained. Validated symbol extraction is mandatory. New imports retain News, Support Pivot, Resistance Pivot, MTF and Game Plan separately when column geometry is reliable, with raw OCR notes/confidence/bounding boxes stored privately for each source row. Historical uploads are never rewritten. A repeated symbol can contribute different source rows; the scanner universe stays deduplicated.

The existing symbol/row OCR is reused. A bounded header pass removes colored backgrounds and printed borders for OCR. The known News/Support/Resistance/Game Plan headings and printed vertical borders locate cells, including the fixture's blank Symbol header and narrow vertical MTF column. Two bounded pivot-column OCR passes recover colored numeric ink missed by sparse OCR. Numeric pivot extraction also requires separate printed cell borders on that row; merged prose rows cannot supply pivot levels simply because OCR finds digits. No ticker or price character corrections are performed. An uncertain vertical MTF heading keeps the original cell text and an Unknown boolean; it cannot influence alerts. Game Plan words are read in visual line order and are not paraphrased.

Numeric pivot cells accept positive decimal prices, optionally `$` prefixed, separated by `/`. All distinct valid levels such as `518/520`, `177/175`, `726.2/725` and `81.6/81.40` are preserved. Prices support at most eight fractional digits without rounding and use the existing canonical decimal representation. Malformed cells, uncertain token/cell boundaries and OCR confidence below 80 yield review warnings and no conditions from that cell. They do not reject another valid optional field, discard a validated symbol, or block an otherwise valid watchlist's activation. Optional header/column OCR failures also fall back safely.

Only literal Game Plan LONG above/over/> price, SHORT below/under/< price and No go under/below price clauses create explicit conditions. No-Go is a warning and belongs to Levels, never Short. Negated/ambiguous directional clauses retain the existing conservative exclusions. Bullish/bearish bias, EMA curls, MTF, PMH/PML/PDC/PDH, targets, gap prose and support/resistance labels never become directional instructions. When geometry is unavailable, the confident original row can supply literal instructions only; it cannot manufacture pivot columns or a structured Game Plan. Historical records without a captured Game Plan display unavailable rather than mislabeling a raw OCR row as that column.

The existing private Daily Watchlist review now shows structured fields and optional-field warnings beside Original Note. Strategy Lab charts, replay and the frozen FORMING detector are not redesigned or changed.

## Monitoring and durability

Only today's activated image upload creates eligible live monitors. Trading date is the ingestion date in America/New_York, using the existing timezone-aware daily scope. Scanner symbol fallback from the previous trading session remains available, but those previous-day levels are ineligible today. Legacy uploads without a recorded trading date cannot silently acquire a new one.

The existing `watchlist_level_monitors` engine, publication lock, per-monitor savepoints, captured provider prices and unique immutable alert keys are reused. No second engine or extra market-data request is introduced. Keys remain date + symbol + semantic + canonical level. Existing LONG/SHORT identities remain unchanged; new SUPPORT, RESISTANCE and NO_GO identities are separate semantics.

| Semantic | Observed condition | First observation |
| --- | --- | --- |
| Explicit Long | previous <= level and current > level | Seeds baseline; equality alone is silent |
| Explicit Short | previous >= level and current < level | Seeds baseline; equality alone is silent |
| No-Go warning | previous >= level and current < level | Seeds baseline; equality alone is silent |
| Support / Resistance | current == level, or previous < level < current, or previous > level > current | Exact equality alerts; a price merely beyond the level seeds baseline |

Each identity alerts at most once per trading date. Recrossing, repeated same-side prices, restarts and same-day refresh/removal/re-addition cannot re-arm an already-triggered identity. Multiple levels for one symbol trigger independently; explicit Long and Short may coexist. Failed/missing provider observations do not clear the cursor. Failed persistence rolls back event and cursor together and leaves other monitors operational. Future, out-of-order, pre-activation and previous-day observations are rejected. No historical prices are replayed to fabricate alerts.

Prices remain sampled closes from the existing provider fetch, not tick-exact touches. Timestamp is the observation time, with the original bar timestamp and provider/feed evidence retained internally. Intermediate touches between scanner polls can be missed. Existing completed-candle eligibility for FORMING remains unchanged; sampled lookout prices do not depend on FORMING or indicator success.

## API and UI

`GET /api/alerts?trading_date=YYYY-MM-DD&category=ALL|LONG|SHORT|LEVEL&limit=200&before_id=ID` extends the existing read-only API. Date defaults to today in New York; category defaults to All. Limit is bounded to 1–200. Results are newest persisted ID first; `next_before_id` supports older history without offset drift. Filters always operate inside the selected trading date. LEVEL includes Support, Resistance and No-Go. Legacy immutable alerts with an original snapshot trading date can be queried without rewriting them; alerts without trustworthy date evidence are omitted.

The display DTO includes ID, symbol, observation timestamp, trading date, level type/direction, supplied price level, observed price, structured Game Plan and supplied support/resistance pivots. It omits raw notes, source upload/row identity, bounding boxes, provider/debug objects, previous prices, strategy versions and thresholds. Original Game Plan and pivots are explicitly authorized trader-facing context. Public dashboard recent alerts now show only today's lookouts. Primary Alerts excludes FORMING; FORMING remains persisted for research/Lab, with existing historical chart compatibility retained. All GETs are presentation-only and never arm monitors or create events.

### Grouped Alerts V2 (implemented, not deployed)

Grouping is presentation only, keyed by `trading_date + symbol`. All/Long/Short/Levels filters apply before grouping, counting and rendering history; LEVEL includes No-Go as well as Support and Resistance. FORMING and records from other dates are excluded. Counts deduplicate persisted IDs (including numeric/string representations); polling cycles do not create events. Groups and history sort by observation timestamp descending, with persisted ID as a tie-breaker.

Each collapsed stock button shows symbol, latest trigger type and actual level, ET time, a neutral count badge and chevron. Native buttons support Enter/Space and `aria-expanded`/`aria-controls`. Only one section opens at a time. It contains Time, Trigger and Observed price columns with tabular numerals, followed by one unchanged original Game Plan. Missing prices/levels/timestamps use `—`; missing plans show a subdued unavailable message. The latest available persisted original plan is used when the latest event lacks one. No plan is rewritten, inferred or combined. Pivot repetition and large individual cards are removed. Mobile rows wrap the summary and allow controlled table scrolling.

Initial date loading follows the existing API's 200-event ID cursor to completion before publishing counts. Each cycle is capped at 20 pages (up to 4,000 events) and the existing 20-second timeout. Partial cycles are discarded. Exceeding limits, invalid cursors or API errors show an explicit complete-history error; prior complete results remain visible with a stale-count warning. Very large dates require a future read-only aggregate approach; no API or schema changes were made here.

Subsequent polls fetch the newest page and continue only until encountering cached persisted history or the end. This relies on the existing immutable persisted alert model and descending ID cursor; it avoids repeatedly fetching the entire historical date. A live burst spanning multiple pages is fetched completely. Polls run 15 seconds after completion; no overlapping polling or WebSockets are added. All categories are fetched so display filters never change sound tracking. Filter/date selections persist, expansion survives refresh and reordering, and it clears when its group disappears. Date changes clear prior-date history. Background refresh never blanks loaded history. Following Today advances at New York midnight with a silent baseline; selecting a past date stays on that date.

`lookoutSound.js`, audio generation, unlock and preference behavior are unchanged. Notification detection runs on newly fetched persisted events before presentation grouping, once per successful new live batch. Initial pagination, older cached history, filters and historical browsing stay silent.

V2 verification: all **24 public frontend Playwright tests passed** in a serial run, including distinct IDs, grouping/order, category/date filters, accordion keyboard operation, missing fields, refresh/expansion, multi-page live bursts, pagination limits, sound regressions and mobile overflow. Production frontend build, Prettier and `git diff --check` passed. No standalone lint script exists in the frontend package. Synthetic desktop/mobile screenshots are generated in ignored `frontend/test-results/`; they are not production-market evidence. Backend tests were not rerun because backend code and schema are unchanged.

V2 requires only the frontend release. No migrations, scanner/engine changes, strategy changes or new public metadata are involved. Frozen FORMING remains `experimental-forming-v1/b067b3150de3`.

For the existing local Compose installation, deployment instructions only:

```sh
docker compose build frontend
docker compose up -d --no-deps frontend
```

Then open Alerts, verify a known date/category against persisted history, expand a stock, check its original plan and verify Sound Off/On using normal live events. Do not inject events into production. Rollback uses the previous frontend image. Production release uses the existing immutable frontend image/operator workflow in [deployment](deployment.md); exact cluster commands belong to the separate deployment repository and are not supplied or executed here. Earlier V1 migration instructions below are historical, not required for V2.

## Optional sound

Sound defaults Off and stores preference under `watchlistLookoutSound` in localStorage, with storage failures handled without affecting alerts. Clicking Sound On creates/resumes Web Audio. Restored On preferences show an explicit **Enable audio in this tab** action because browser interaction may still be required. No external audio file, OS daemon or notification service is used.

A short 0.36-second two-note sine tone plays once per batch containing an unseen persisted ID above the live baseline. It never loops. The first successful load is always silent, including restored sound preferences and returning from historical browsing. Seen IDs persist across Alerts mounts in the browser tab. Repeated polls, display filter changes, already-seen IDs, historical dates, older-history loads and Sound Off never replay audio. Failures/suspended contexts display an audio-unlock message while visual alerts continue. The feature does not promise delivery while the page is closed, background timers are throttled, the browser suspends audio or the network is unavailable.

## Additive migration and verification

Migration **0016** adds nullable `watchlist_symbols.structured_rows`, monitor `semantic` and `watchlist_details`, and indexed nullable `alerts.trading_date`. Existing records, snapshots, monitor keys and alert immutability protection remain unchanged. No application/production migration was run during implementation. New extraction applies to future imports only; existing watchlists and alert history are not backfilled.

`tests/test_lookout.py` covers table/price parsing, real-fixture geometry, optional-cell confidence, directional/generic/equality/No-Go rules, multiple-level deduplication, date boundaries, original plan/DTO privacy, pagination, read-only browsing and legacy date evidence. Existing monitor, FORMING, persistence/failure and restart tests remain. `frontend/tests/lookout.spec.js` covers live ID tracking, batching, filters, dates, initial silence, preference restoration, Sound Off, failed audio and midnight rollover.

Final verification: **253/253 backend tests passed on disposable PostgreSQL**, including real screenshot OCR, row-cell evidence, migrations and concurrent publication. SQLite ran **253 tests with 4 expected environment skips** (the two PostgreSQL concurrency checks and two real-Tesseract checks). The public frontend passed **19/19** browser tests in a serial run; the private frontend passed **15/15**. Both production builds and Prettier checks passed, as did Python compileall and git diff --check. Earlier concurrent Chrome startup attempts timed out before individual test setup; serial public verification passed. Ignored local logs are retained in `data/lookout-verification/`. Disposable test resources were removed after verification.

Changed implementation files:

- Backend: `backend/alerts.py`, `backend/api.py`, `backend/database/models.py`, `backend/level_alerts.py`, `backend/service.py`, `backend/store.py`.
- Extraction: `ripster_scanner/watchlist.py`, `ripster_scanner/watchlist_image.py`, `ripster_scanner/watchlist_levels.py`, new `ripster_scanner/watchlist_table.py`.
- Migration: new `migrations/versions/0016_watchlist_lookout.py`.
- Public UI: `frontend/src/Alerts.jsx`, `frontend/src/lookoutSound.js`, `frontend/src/App.jsx`, `frontend/src/components.jsx`, `frontend/src/pages.jsx`, `frontend/src/styles.css`.
- Staged private review: `strategy-lab-frontend/src/DailyWatchlist.jsx` (fields/warnings only, no Lab redesign).
- Tests/tools: `tests/test_lookout.py`, `tests/test_alerts.py`, `tests/test_api.py`, `tests/test_level_alerts.py`, `tests/fixtures/watchlist-column-ocr.json`, `frontend/tests/lookout.spec.js`, `frontend/tests/dashboard.spec.js`, `docker-compose.lookout-test.yml`, `tools/inspect_lookout.py`.
- Documentation: `README.md`, `docs/architecture.md`, `docs/frontend.md`, `docs/security.md`, `docs/watchlist-level-alerts.md`, this document, `docs/images/watchlist-lookout-alerts.png`, `tools/README.md`.

For disposable PostgreSQL verification only:

```sh
docker compose -p market-scanner-lookout-tests -f docker-compose.lookout-test.yml up --abort-on-container-exit --exit-code-from test
docker compose -p market-scanner-lookout-tests -f docker-compose.lookout-test.yml down
```

This fixture uses a separate project/network, tmpfs PostgreSQL data, test-only credentials, no exposed host ports, no application volumes and read-only source mounts. It uses the existing local Python image's dependencies; build that image first if unavailable. Never substitute a production database for this fixture.

## October 5 read-only validation status

The user supplied expected source content for CBRS (Support 173; Resistance 177/175; No go under 173 and Long over 175) and MSFT (Support 518/520; Resistance 522; Bullish bias with Software). Those expectations produce five independent CBRS semantic identities and three generic MSFT pivot identities in synthetic tests. They are not evidence that production monitors or historical alerts existed.

The inspected **local Compose database** was at migration **0012**, with active upload ID 12, no level-monitor table, no structured trading-date fields and no October 5 uploads by legacy bookkeeping date. Therefore CBRS/MSFT production extraction, monitor state, triggered status and alert timestamp/price could not be established from that database. Production location/access was requested; none was supplied during this inspection. This is an outstanding validation limitation, not proof of no production alerts. No current activated upload or database record was changed.

`tools/inspect_lookout.py` can be run in the existing authorized production application environment. It explicitly starts a PostgreSQL READ ONLY transaction, uses a 10-second statement timeout, handles old schemas, queries only allowed watchlist/monitor/alert evidence for CBRS/MSFT, and never prints credentials or changes schema/data. A read-only runtime invocation must use existing server-side configuration, not copied credentials. Obtain production results before claiming October 5 validation complete. Do not reconstruct/backfill alerts for crossings that occurred before an eligible live monitor existed.

Additional measured discrepancies concern the **September 21 repository fixture**, not today's source: the sparse OCR missed red Resistance Pivot values and read a vertical MTF heading imperfectly. Targeted extraction recovered MRVL 252.4, COIN 205.5, TSLA 371, NFLX 72/72.20 and MSFT 396.4 in fixture verification. MTF remained Unknown with review warnings. MRVL News OCR reads “Al” where the image says “AI”; that source text is retained without speculative correction. No other October 5 source-image versus persisted-data comparisons were possible without its actual production records/image.

## Deployment steps — instructions only, not executed

For this repository's local Compose installation, when separately authorized:

1. Review changes and preserve a verified database backup using the existing operator backup procedure. Keep the old application image available; do not reset the database or downgrade historical columns.
2. Stop schema consumers: `docker compose stop scanner research backend internal-backend`.
3. Build the application and frontends: `docker compose build backend frontend strategy-lab`.
4. Run the existing migration service once: `docker compose run --rm migrate python -m alembic upgrade head`. Verify version **0016** using the migration tool; do not manually update Alembic metadata.
5. Start the updated services: `docker compose up -d backend internal-backend scanner research frontend strategy-lab`.
6. Read `/health`; query `/api/alerts?trading_date=YYYY-MM-DD&category=ALL` for a known persisted date; open Alerts and verify date/filter/sound controls. Inspect current monitors read-only. Do not generate fake production prices or alerts for a smoke test.
7. For a subsequent day's normal upload, review structured fields and warnings before activation. Existing activated uploads are not automatically rewritten, reparsed or reactivated by deployment. Their new generic pivots will remain unavailable until a normally reviewed future upload supplies structured fields. Do not silently alter today's upload to validate this release.

Production uses immutable GHCR release tags and the separate `homelab-k3s` repository, as described in [deployment](deployment.md). After a reviewed successful image release, the operator runs its existing migration Job with the matching application image before rolling out backend/internal-backend/scanner/research and both frontend images. Exact cluster resource commands depend on that separate repository and were not inspected or invented here. No publication, deployment, Kubernetes, Cloudflare or production-data changes were performed by this task.
