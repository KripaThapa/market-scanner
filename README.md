# Market Scanner

A deterministic, rule-based market scanner with a React read-only client, FastAPI public API, PostgreSQL, scanner and nightly research workers. The current market-data provider is Alpaca/IEX. Discovery V1 merges an uploaded watchlist with Alpaca Screener Most Actives, Top Gainers, and Top Losers when available. Experimental Forming Setup V1 is a research heuristic, not an entry signal or official trading grade.

## Local development

1. Copy `.env.example` to `.env` and set PostgreSQL and Alpaca credentials. `.env` is ignored by Git. Do not put secrets in Vite variables or React source.
2. Run `docker compose up --build`.
3. Open the public scanner at `http://127.0.0.1:${FRONTEND_PORT:-3000}` and the private Strategy Lab at `http://127.0.0.1:${STRATEGY_LAB_PORT:-3003}`. Both bind to loopback for local development.

Compose starts migration, PostgreSQL, public and internal backends, scanner worker, nightly research worker, public frontend, and private Strategy Lab frontend. Public frontend/backend and Strategy Lab ports bind to loopback; PostgreSQL, workers, and the internal backend expose no host ports. The Compose frontends serve compiled assets through unprivileged Nginx. External deployment still requires the controls in [security](docs/security.md).

The public UI has Dashboard, Discovery, Forming Setups, Sectors, Alerts, Settings, and symbol OHLCV detail charts. It receives sanitized display data only. Upload, Rules, Research, provenance, and Strategy Lab are private/admin functions. Compose mounts the internal API only on its private network so the loopback-only Strategy Lab frontend can proxy to it. Authentication and ADMIN/RESEARCHER authorization are still required before any private service is exposed externally. For local test data, set `SCANNER_JSON_FALLBACK=true` and edit `config/watchlist.json`; the existing uploaded watchlist remains in PostgreSQL.

## Configuration

| Variable | Default | Use |
| --- | --- | --- |
| `MARKET_DATA_PROVIDER` | `alpaca_iex` | Provider-neutral scanner adapter selection; Alpaca/IEX only currently |
| `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` | empty | Server-side market data and screener credentials |
| `DISCOVERY_ENABLED` | `true` | Automatic discovery during research window |
| `DISCOVERY_INTERVAL_SECONDS` | `300` | Minimum interval between source refresh attempts |
| `DISCOVERY_TOP_N` | `10` | Screener result count requested |
| `TRADING_WINDOW_START`, `TRADING_WINDOW_END`, `TRADING_TIMEZONE` | `08:00`, `10:00`, `America/Chicago` | Research observation window, start inclusive/end exclusive |
| `NIGHTLY_ANALYSIS_TIME`, `NIGHTLY_ANALYSIS_TIMEZONE` | `18:00`, `America/Chicago` | Daily outcome job |
| `SCANNER_INTERVAL_SECONDS` | `60` | Scan cycle interval |
| `PUBLIC_RATE_LIMIT_PER_MINUTE` | `120` | Per-client public API request limit |
| `PUBLIC_EXPENSIVE_RATE_LIMIT_PER_MINUTE` | `30` | Per-client symbol/chart request limit |
| `CORS_ALLOWED_ORIGINS` | local frontend | Explicit browser origins; wildcard rejected |
| `TRUSTED_HOSTS` | local hosts/backend | Explicit HTTP Host allowlist; set the reverse-proxy hostname in deployment |
| `FRONTEND_PORT` | `3000` | Loopback host port for local frontend |
| `STRATEGY_LAB_PORT` | `3003` | Loopback host port for private Strategy Lab |
| `REPLAY_TIMEZONE`, `REPLAY_START`, `REPLAY_END` | `America/Chicago`, `08:00`, `10:00` | Generic/futures replay default window |
| `REPLAY_EQUITY_START` | `08:30` | Normal equity replay start; end uses `REPLAY_END` |
| `REPLAY_WARMUP_CALENDAR_DAYS` | `7` | Indicator warm-up retained privately, allowed 1–30 |
| `BASELINE_NIGHTLY_ENABLED` | `true` | Run missing frozen-strategy baseline days after nightly outcomes |
| `BASELINE_MAX_CATCHUP_TRADING_DAYS` | `5` | Maximum completed XNYS sessions checked by nightly catch-up |
| `BASELINE_PROVIDER_RETRIES`, `BASELINE_RETRY_DELAY_SECONDS` | `3`, `2` | Bounded historical-provider retry/backoff |

The four experimental forming thresholds and their formulas are documented in [strategy](docs/strategy.md). Optional read-only `config/sectors.json` maps symbols to sectors; missing mappings remain UNKNOWN. Alpaca's asset object does not currently supply sector/industry for this implementation. The scanner still processes UNKNOWN symbols.

## Research and operations

Scanner Reliability V1 applies 5-second HTTP connect and 20-second read-inactivity
timeouts to live Alpaca candle/discovery requests. Private logs include cycle IDs,
symbol/stage progress, durations, and sanitized failure categories. Processing
remains sequential. See [architecture](docs/architecture.md#scanner-reliability-v1--implemented)
for the SDK integration, heartbeat meaning, and remaining unbounded operations.

The 08:00–10:00 Central window is for setup observations, **not** a cutoff for retaining future candle data. Append-only observations cover every active-universe symbol, including NONE states. Each stores strategy version, data provenance, discovery overlap, sector and execution-candle state. The nightly job computes objective future returns and excursions, without changing rules or declaring wins/losses. Run an idempotent backfill inside Docker with:

```sh
docker compose run --rm research python -m research.job --date 2026-09-18
```

Private research/rules/replay endpoints are not host-published; the local Strategy Lab proxies to the internal container. Do not expose this private UI or internal app beyond loopback until authentication is added. Proposed rules are hypotheses and cannot mutate production scanner logic.

Strategy Lab V1 persists a one-minute historical snapshot, advances on completed 3m boundaries, rebuilds the current 10m candle from only known minutes, and records `NOT_YET`, `INTERESTING`, or `WOULD_CONSIDER_ENTRY` with free text. Equity replay is implemented. MES replay is unavailable because Alpaca/IEX has no futures historical-data client; V1 returns a capability error rather than substituting data. See [Strategy Lab](docs/strategy-lab.md).

Equity replay dates are validated against the XNYS exchange calendar. Weekend and market-holiday selections return `MARKET_CLOSED` with adjacent trading days; an expected-open date with no usable provider bars returns the separate `NO_DATA` condition. Futures do not inherit the equity calendar.

Historical Strategy Baseline V1 replays the frozen Experimental Forming Setup V1 over every completed 3-minute decision point from 08:30 through before 10:00 CT for symbols recorded in that day's historical universe. It groups consecutive equal FORMING states into episodes and measures objective 3/5/10-bar movement plus favorable/adverse excursion. These are setup statistics, not entries, trades, or win rates. Run the restartable 20-session job explicitly with:

```sh
docker compose --profile tools up -d --build --force-recreate baseline
docker compose logs -f baseline
```

For a bounded smoke range use `docker compose --profile tools run --rm baseline python -m research.baseline --start YYYY-MM-DD --end YYYY-MM-DD`. Results are private at `http://127.0.0.1:${STRATEGY_LAB_PORT:-3003}` under **Historical baseline** and at `/api/internal/strategy-lab/baseline` through that loopback UI proxy. See [research](docs/research.md).

The private replay form defaults to the latest completed XNYS session, offers previous/next trading-day navigation, and searches symbols recorded by the scanner/discovery system on that selected date. It does not use today's universe or outcome data. When no historical universe exists, manual symbol entry is available. Equity sessions default to 08:30–10:00 CT with optional custom times; MES retains separate controls and remains unavailable until a futures provider is configured.

## Verification

```sh
.venv/bin/python -m unittest discover -s tests
npm test --prefix frontend
npm run build --prefix frontend
npm run format:check --prefix frontend
npm test --prefix strategy-lab-frontend
npm run build --prefix strategy-lab-frontend
docker compose up -d --build
docker compose ps
```

For dependency review use `npm audit --prefix frontend` and, in a controlled Python environment, `python -m pip_audit` after installing `pip-audit`. Review findings and rerun tests before updating dependencies. Container images also need scanning as part of a production pipeline.

## Documentation

Image releases follow **GitHub Actions → GHCR → SHA release tag**. The separate
`homelab-k3s` repository owns **release tag → Kubernetes deployment**. This
repository contains no Kubernetes manifests or cluster deployment scripts; see
[deployment and release handoff](docs/deployment.md).

- [Architecture](docs/architecture.md): provider flow, persistence, services, API boundary.
- [Strategy](docs/strategy.md): exact existing classifier and Experimental Forming Setup V1.
- [Discovery](docs/discovery.md): source merging, history, sectors, candle state.
- [Research](docs/research.md): observations, leakage prevention, outcomes.
- [Frontend](docs/frontend.md): public client behavior.
- [Security](docs/security.md): threat model and deployment requirements.
- [Strategy Lab](docs/strategy-lab.md): private visual replay and hard no-look-ahead boundary.

Not implemented: NEAR_ENTRY, entry trigger, buy/sell signals, automated trading, automatic rule modification, AI/LLM research agent, ML/Transformer models, automated optimization, sector strength trading rules, market mover performance ranking, Finviz integration, options flow, news scoring, or Telegram alerts.
