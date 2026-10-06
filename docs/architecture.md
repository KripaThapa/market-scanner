# Architecture

**IMPLEMENTED — Lab V1 read model:** `strategy_lab/review.py` reads existing watchlist, research candle, immutable alert, completed live-baseline episode and outcome records through batched SQL queries. The internal app alone serves `GET /api/internal/strategy-lab/review/watchlist` and `/review/chart`. The public app has no review routes. DTOs omit provider/debug metadata and strategy configuration; underlying evidence is retained. Review never runs a detector, fetches provider data or writes historical records. See [chart review](strategy-lab.md#daily-chart-review) for candle revision and outcome semantics.

## Data flow

```text
Selected daily upload ─┐
Market context ────────┤
Most Actives (opt-in) ─┤
Top Gainers (opt-in) ─┼─> normalized active universe ─> sector metadata
Top Losers (opt-in) ──┘                                  │
                                                        v
Alpaca/IEX -> MarketDataProvider -> normalized 1m candles -> 3m/10m aggregation
                                                        │
                                                        v
                                  existing indicators/context/forming detector
                                                        │
                         ┌──────────────────────────────┴────────────────────┐
                         v                                                   v
                 sanitized public DTOs                           historical observations,
                 and OHLCV charts                               candles, discovery/sector
                                                                 history, nightly outcomes
```

The scanner worker selects one activated upload (today, otherwise exactly the previous XNYS session), adds SPY/QQQ/MAGS and the seven individual MAG7 stocks, refreshes explicitly enabled discovery sources independently, merges symbol membership, scans each symbol once, and publishes scan results. The market-data provider boundary isolates Alpaca SDK bars from aggregation, indicators, context, forming detection, collection, and outcomes. Alpaca/IEX remains the only candle provider. Alpaca Screener supplies Most Actives and Market Movers (gainer/loser) when the account permits; its source metadata is separate from IEX feed metadata. Provider failure is recorded per source and does not stop other sources.

Automatic discovery defaults off through `AUTO_DISCOVERY_ENABLED=false`. Historical uploads remain stored; older uploads never accumulate into the active universe. Previous-session fallback copies membership only, never daily level triggers. VIX spot data is unsupported by the stock/IEX pipeline. See [universe selection](discovery.md). No migration is required for this configuration/selection change.

## Scanner Reliability V1 — IMPLEMENTED

Live worker and CLI candle clients, the default Alpaca/IEX adapter, and the
discovery screener use `ripster_scanner/alpaca_http.py`. Pinned `alpaca-py==0.44.0`
does not expose constructor connect/read timeouts. Small client subclasses
override its `_one_request` hook to copy request options and pass
`timeout=(5, 20)` to the SDK's existing `requests.Session.request` call. This is
instance-scoped: no global patch, new transport, or dependency. SDK upgrades must
revalidate this private hook with the transport tests. Injected custom clients
remain the caller's responsibility. Historical replay/baseline clients and the
watchlist asset-directory/OCR path are unchanged.

The SDK retains three retries with three-second sleeps for HTTP 429/504 (four
attempts total per page); connect/read timeout exceptions propagate immediately
to existing handlers. A symbol timeout produces the existing failed-symbol result
and scanning proceeds sequentially. A discovery timeout retains last-known
membership and marks that source FAILED; remaining sources still run, including
the existing retry of movers for losers if the gainers fetch failed. No universe,
strategy, or public DTO semantics change. Successful calculations and default
strategy identity remain `experimental-forming-v1/b067b3150de3`.

Each `run_once` gets a random cycle ID. Private logs report cycle start/completion,
uploaded-universe count, discovery start/completion and per-source progress,
every symbol start/completion/failure, and publication start/completion. Durations
use a monotonic clock. Fixed error categories exclude exception messages,
credentials, headers, URLs, and response bodies. `cycle_completed outcome=failed`
means a handled failure returned; `published=False` means a newer watchlist
superseded the result. Early empty/busy cycles omit stages they did not execute.

The database heartbeat is unchanged: it updates at cycle entry and in cycle
cleanup, not continuously during requests. It measures those progress points,
not process liveness. Handled symbol timeouts allow publication and the final
heartbeat/status update; a busy lock attempt does not update it. The configured
scanner interval is a delay after the cycle, not a deadline.

V1 is not a hard wall-clock guarantee. The read timeout limits socket inactivity,
not total response duration. DNS resolution, slow trickling responses, unlimited
SDK pagination, database statements/locks/pre-ping/commit/rollback, filesystem
or logging I/O, and local calculations still lack a total deadline. No process
isolation, concurrency, watchdog, schema change, or database timeout is introduced.
Those remain later reliability phases. Tests inject transport timeouts without
external requests or sleeps; they verify handling and timeout propagation, not
real elapsed network timing.

The existing deterministic Experimental Forming Setup V1 remains unchanged. A 10m candle gives context; 3m candles give setup development. The worker records whether the execution 3m candle was PARTIAL or COMPLETED and whether existing behavior considered it decision-eligible. The latest 3m candle may be partial. Candle timestamps are opening times.

PostgreSQL migrations 0001–0005 preserve prior scanner/research tables. Migration `0006_discovery_sector_candle_state` adds `discovery_memberships`, `discovery_events`, `discovery_source_status`, `symbol_metadata`, `active_universe_members`, `sector_snapshots`, and `research_observation_sources`, plus nullable observation sector/candle-state/eligibility/snapshot links. Old observations retain unknown metadata. Membership tracks current same-day status; events preserve transitions; observation-source rows preserve overlap. Sector snapshots store objective counts. Indexed symbol/date/time/state fields support research queries.

Research observations are append-only evidence keyed to completed/evaluated candle and strategy version. The collector caps features at the evaluation instant; future candles are retained separately and used only by the nightly outcome worker. The nightly worker runs at the configured local time and can be backfilled through Docker. It calculates objective forward returns/excursions, not win/loss or recommendations. See [research](research.md).

Strategy Lab adds a separate historical capability: `HistoricalMarketDataProvider → persisted normalized 1m replay snapshot → ReplayClock → BoundedMarketView(as_of=T) → aggregation/indicators/context → private replay DTO`. Provider fetching and storage may contain later candles, but calculation code only accepts the bounded view. Migration `0007_strategy_lab_replay` adds replay sessions, frozen source candles, and human observations without modifying existing history. The same boundary is intended for a future deterministic backtester. See [Strategy Lab](strategy-lab.md).

Historical Strategy Baseline V1 reuses that exact replay service and bounded calculation path. Migration `0008_historical_strategy_baseline` adds restartable run/day/symbol checkpoints, candle-level evidence, and distinct FORMING episodes. A symbol/date/config combination is unique, each evaluation timestamp is unique within it, and every unit commits incrementally. Outcome calculation is invoked only after the bounded decision evidence is saved. The explicit `baseline` Compose tools profile runs backfills; normal startup never launches a full historical backfill. The existing nightly worker checks a bounded completed-session catch-up range and processes missing symbol-days chronologically.

Equity replay creation first passes through the provider-neutral market-session boundary backed by the XNYS `exchange-calendars` calendar. Closed sessions stop before provider access and return `MARKET_CLOSED`; an expected-open session with no provider candles returns `NO_DATA`. Futures bypass this equity calendar and will require their own provider/session implementation.

Private replay-creation metadata follows two additional read paths: `XNYS calendar → private month/adjacent-day DTO` and `historical observations + discovery memberships + persisted universe → selected-date symbol catalog`. The catalog uses an exact trading-date predicate and does not join outcomes, so replay selection cannot rank or reveal symbols using later market movement. These routes exist only in `backend.internal_api`.

The live equity scanner previously filtered Alpaca/IEX data to 09:30–15:59 America/New_York, which removed 08:00–08:30 Central from the configured research window. It now retains provider-supplied extended-hours bars. Aggregation remains day-aligned with opening timestamps: 3m buckets open at minute 00/03/06 and 10m buckets at 00/10/20. Existing VWAP resets on each America/New_York calendar date. Futures session/VWAP semantics remain a separate unsupported capability rather than inheriting equity rules.

## API and deployment boundary

The application repository builds and publishes three SHA-tagged GHCR images
through GitHub Actions. The separate `homelab-k3s` repository owns Kubernetes
manifests and manual Raspberry Pi deployment. No cluster deployment runs here.
See [deployment](deployment.md) for release gates and handoff.

Compose starts PostgreSQL, migration, public backend/frontend, private internal backend/Strategy Lab frontend, scanner, and research. Public frontend/backend and Strategy Lab bind to loopback. PostgreSQL, workers, and internal backend have no host ports. The public `backend.api:create_app` exposes sanitized scanner DTOs. `backend.internal_api:create_internal_app` contains private rules/research/replay/source-status/upload routes and is reachable only through the local private frontend proxy. This keeps private payloads and code out of the normal React client. Authentication and role enforcement are required before external private access. See [security](security.md).

Configuration: `.env` supplies database/provider credentials, discovery refresh, research window, forming thresholds, CORS, and public rate limits. Sector Enrichment V1 uses a persistent provider-neutral reference cache with FMP as its first adapter; `config/sectors.json` is fallback only. See [metadata architecture and history policy](sector-enrichment.md). No Finviz scraping, sector trading rule, entry signal, automated orders, or AI analysis is present.

## Alert Foundation V1 — IMPLEMENTED

```text
Scanner state (unchanged experimental strategy)
    ↓ completed, decision-eligible 3m observation
FORMING transition (durable per symbol + strategy version)
    ↓
Alert Event → immutable alert-time snapshot → Web display
```

`alerts` was previously an unused delivery-shaped table. Migration `0013`
extends it with a strategy-version foreign key, transition number, decision
candle opening timestamp and JSON snapshot. Existing rows retain NULL evidence;
no historical metrics or events are reconstructed. A unique
`(symbol, strategy_version, transition_number)` identity prevents duplicates.
PostgreSQL and SQLite triggers prohibit UPDATE/DELETE of new event rows,
including their timestamps and snapshots. Legacy delivery columns remain unused.

Operational `forming_setups` are mutable, upload-scoped records that can reset
on failed data and do not split direct direction changes. Those semantics remain
unchanged. A small `alert_states` table instead retains the last confirmed state,
last decision candle/evaluation times and event sequence per symbol and strategy
version. It is deliberately independent of watchlist activation, worker lifetime,
research-window membership and operational episode IDs. No existing structure
provided this completed-observation lifecycle.

Only successful observations with both current frame summaries and known candle
evidence can advance alert state. The actual latest 3m decision candle must be
COMPLETED at the scanner evaluation time (or publication time when evaluation
time is unavailable), capped at publication time. Future-dated frame evidence,
PARTIAL observations, missing data and errors do not advance or clear state.
The initial confirmed FORMING observation creates an event. Repeating the same
direction does not; a completed NONE rearms it; a direct completed opposite
direction creates a new event. Removals, uploads, daily rollover and restarts do
not rearm alerts. Out-of-order candles/evaluations and exact observation repeats
are ignored. A later observation of a revised completed candle may change state;
previous events remain immutable and are never backdated or rewritten.

The existing publication AppState lock serializes concurrent publishers. Alert
processing occurs after the normal scan writes. Each eligible symbol has a
savepoint containing its event and cursor update. An alert write failure rolls
back that pair, logs only the symbol and a fixed error category, and allows other
symbols and publication to proceed. The next eligible observation retries from
the retained state; it captures its own current evidence, not the lost earlier
snapshot. A full publication rollback also rolls back all its alerts. Superseded
publications produce no alerts. Database outages retain the existing worker
retry behavior; V1 adds no total database deadline, external calls or deliveries.
Reliability V1 HTTP timeouts, progress logging and failure continuation are intact.

Snapshot schema 1 copies the scanner's 3m/10m candle timestamps, close, EMA5/12/34/50,
VWAP, volume and contexts, plus 3m alert price, setup state, sector, original
FORMING reason, evaluated/known-at times, COMPLETED candle state and explicit
`decision_eligible=true`. Available provider/feed, 1m source timeframe, session
policy and market timezone are private. Missing values stay NULL/UNKNOWN.
The alert row supplies ID, symbol, state, creation time and strategy version.
Alert creation time is the publication-time event boundary; decision-candle time
is its earlier candle opening time, used only for chart placement. Future outcome
windows must begin after the alert boundary, never at the candle opening.

`/api/dashboard` and `/api/alerts` now return only Watchlist Lookout events for
the selected New York trading date (today on Dashboard). The extended explicit
allowlist includes supplied levels, their semantics, observed price and original
structured Game Plan/pivots; raw detector reasons and snapshots remain private.
The existing FORMING persistence and research paths remain unchanged.
The existing public stock detail/chart API adds only persisted marker IDs, states,
alert timestamps and decision-candle timestamps for exact visible 3m candles
(up to 1,000 events). No private chart endpoint was needed. Markers are independent
of mutable operational setup records and remain visible after a state closes,
while their candles remain in the chart. UTC epoch seconds locate candles;
America/New_York formatting displays ET with DST. Lightweight Charts 5's
`createSeriesMarkers` places FORMING LONG below and FORMING SHORT above candles.

The scanner still evaluates its latest candle, which may be partial. V1 does
not recalculate earlier completed candles or alter scanner timing. Consequently,
only completed observations actually seen by the live scanner can emit alerts;
this is not exhaustive coverage of all historical completed candles. At upgrade,
the first eligible FORMING observation seeds state and creates an event; existing
operational episodes/research rows are not used to invent prior alert state.
Events survive chart-window expiry and symbol removal, though the current stock
route remains available only for symbols in the active scan. Dashboard refresh
remains the existing 15-second polling mechanism.

### Future extension points — PROPOSED, NOT IMPLEMENTED

```text
Alert Event
    ├── Web (implemented)
    └── Discord delivery adapter (future)

Alert Event → Outcome Evaluator → MFE / MAE
            → 10 / 20 / 30 / 50% thresholds → Backtest / rule analysis
```

A future delivery adapter reads committed event IDs and keeps delivery attempts
in separate storage, without mutating alerts or putting Discord logic in strategy.
No Discord SDK, webhook, secret, HTTP call or delivery worker is included.
A future outcome table can reference `alerts.id` and record actual directional
MFE/MAE, threshold attainment and time-to-threshold. Direction is mirrored for
shorts. The evaluation window and handling of missing post-alert data remain TBD.
The tentative primary HIT definition is a 30% favorable move; 50% denotes a larger
move. **FORMING alert != trade entry. +30% future HIT definition != alert trigger.**
No HIT/MISS evaluator, simulated trades or Backtest is implemented here.
Default strategy identity remains `experimental-forming-v1/b067b3150de3`.

Deployment handoff: apply additive migration `0013` before starting the updated
backend/scanner. This milestone does not run that migration against the application
database. Preserve the schema on an application rollback: downgrading `0013` would
remove alert evidence and durable state and must not be used after recording alerts.

Sector Enrichment V1 adds migration `0014`, extending the existing reference cache and published universe industry field. FMP → SymbolMetadataProvider → SymbolMetadataService → persistent cache → scanner/research/alerts. It does not alter Alert Foundation transitions or historical snapshots.

Watchlist Level Alerts V1 (`0015`): validated upload → fixed New York ingestion
trading_date → whole-watchlist activation → durable level monitors → existing
Alpaca/IEX one-minute close observations → immutable level events → web alerts.
No FORMING, EMA, VWAP, volume or sector gate participates. See
[level identity, expiry, price source and limitations](watchlist-level-alerts.md).

**Watchlist Lookout Alerts V1 (`0016`)** extends that same engine: table-aware optional extraction → structured pivots/Game Plan → whole-watchlist activation → existing monitors → immutable attention events → date/category API → live polling and optional browser audio. SUPPORT/RESISTANCE first-touch/cross and explicit NO_GO warnings are separate semantics from LONG/SHORT. Daily key identity and savepoint/refresh/restart protections remain. Migration 0016 is additive only and never backfills existing uploads/alerts. FORMING remains persisted for Lab/research and is excluded from primary Alerts. See [Lookout rules, privacy, migration and deployment](watchlist-lookout-alerts.md).
