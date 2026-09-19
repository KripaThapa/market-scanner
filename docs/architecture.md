# Architecture

## Data flow

```text
Uploaded watchlist ─┐
Most Actives ────────┤
Top Gainers ─────────┼─> normalized active universe ─> sector metadata
Top Losers ──────────┘                                  │
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

The scanner worker refreshes eligible discovery sources independently, merges symbol membership, scans each symbol once, and publishes scan results. The market-data provider boundary isolates Alpaca SDK bars from aggregation, indicators, context, forming detection, collection, and outcomes. Alpaca/IEX remains the only candle provider. Alpaca Screener supplies Most Actives and Market Movers (gainer/loser) when the account permits; its source metadata is separate from IEX feed metadata. Provider failure is recorded per source and does not stop other sources.

The existing deterministic Experimental Forming Setup V1 remains unchanged. A 10m candle gives context; 3m candles give setup development. The worker records whether the execution 3m candle was PARTIAL or COMPLETED and whether existing behavior considered it decision-eligible. The latest 3m candle may be partial. Candle timestamps are opening times.

PostgreSQL migrations 0001–0005 preserve prior scanner/research tables. Migration `0006_discovery_sector_candle_state` adds `discovery_memberships`, `discovery_events`, `discovery_source_status`, `symbol_metadata`, `active_universe_members`, `sector_snapshots`, and `research_observation_sources`, plus nullable observation sector/candle-state/eligibility/snapshot links. Old observations retain unknown metadata. Membership tracks current same-day status; events preserve transitions; observation-source rows preserve overlap. Sector snapshots store objective counts. Indexed symbol/date/time/state fields support research queries.

Research observations are append-only evidence keyed to completed/evaluated candle and strategy version. The collector caps features at the evaluation instant; future candles are retained separately and used only by the nightly outcome worker. The nightly worker runs at the configured local time and can be backfilled through Docker. It calculates objective forward returns/excursions, not win/loss or recommendations. See [research](research.md).

Strategy Lab adds a separate historical capability: `HistoricalMarketDataProvider → persisted normalized 1m replay snapshot → ReplayClock → BoundedMarketView(as_of=T) → aggregation/indicators/context → private replay DTO`. Provider fetching and storage may contain later candles, but calculation code only accepts the bounded view. Migration `0007_strategy_lab_replay` adds replay sessions, frozen source candles, and human observations without modifying existing history. The same boundary is intended for a future deterministic backtester. See [Strategy Lab](strategy-lab.md).

Historical Strategy Baseline V1 reuses that exact replay service and bounded calculation path. Migration `0008_historical_strategy_baseline` adds restartable run/day/symbol checkpoints, candle-level evidence, and distinct FORMING episodes. A symbol/date/config combination is unique, each evaluation timestamp is unique within it, and every unit commits incrementally. Outcome calculation is invoked only after the bounded decision evidence is saved. The explicit `baseline` Compose tools profile runs backfills; normal startup never launches a full historical backfill. The existing nightly worker checks a bounded completed-session catch-up range and processes missing symbol-days chronologically.

Equity replay creation first passes through the provider-neutral market-session boundary backed by the XNYS `exchange-calendars` calendar. Closed sessions stop before provider access and return `MARKET_CLOSED`; an expected-open session with no provider candles returns `NO_DATA`. Futures bypass this equity calendar and will require their own provider/session implementation.

Private replay-creation metadata follows two additional read paths: `XNYS calendar → private month/adjacent-day DTO` and `historical observations + discovery memberships + persisted universe → selected-date symbol catalog`. The catalog uses an exact trading-date predicate and does not join outcomes, so replay selection cannot rank or reveal symbols using later market movement. These routes exist only in `backend.internal_api`.

The live equity scanner previously filtered Alpaca/IEX data to 09:30–15:59 America/New_York, which removed 08:00–08:30 Central from the configured research window. It now retains provider-supplied extended-hours bars. Aggregation remains day-aligned with opening timestamps: 3m buckets open at minute 00/03/06 and 10m buckets at 00/10/20. Existing VWAP resets on each America/New_York calendar date. Futures session/VWAP semantics remain a separate unsupported capability rather than inheriting equity rules.

## API and deployment boundary

Compose starts PostgreSQL, migration, public backend/frontend, private internal backend/Strategy Lab frontend, scanner, and research. Public frontend/backend and Strategy Lab bind to loopback. PostgreSQL, workers, and internal backend have no host ports. The public `backend.api:create_app` exposes sanitized scanner DTOs. `backend.internal_api:create_internal_app` contains private rules/research/replay/source-status/upload routes and is reachable only through the local private frontend proxy. This keeps private payloads and code out of the normal React client. Authentication and role enforcement are required before external private access. See [security](security.md).

Configuration: `.env` supplies database/provider credentials, discovery refresh, research window, forming thresholds, CORS, and public rate limits. `config/sectors.json` may map symbols to sectors; unmapped symbols are UNKNOWN. No Finviz scraping, sector trading rule, entry signal, automated orders, or AI analysis is present.
