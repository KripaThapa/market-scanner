# Public scanner frontend

The React client is untrusted. It renders server-classified results and never computes context, forming state, sector decisions, or strategy thresholds. The shared UI is source-agnostic and read-only.

Pages: Dashboard (Stocks scanned, Scanner results, known-sector and forming counts), Discovery (active universe, sector filter, symbol navigation), Forming Setups (active states), Sectors (objective counts and symbol drill-down), Alerts (completed-candle FORMING events), Settings (non-editable status), and `/symbols/{symbol}` (scanner-backed 3m/10m OHLCV candlesticks). The symbol chart shows raw scanner-persisted candles for visual context. EMA/VWAP calculations and detector reasons remain internal. There is no browser-side independent market-data fetch.

Public navigation has no Watchlist upload, Rules, Research, or Strategy Lab page. This is required because those workflows reveal private inputs, research metadata, or rule definitions. The internal app runs only on the private Compose network; local operators can use the JSON fallback while authenticated management is designed. Public React source and production bundle must contain no provider keys, discovery source provenance, strategy thresholds, replay logic, or research records.

Strategy Lab is a separate React build in `strategy-lab-frontend/`; none of its routes or source are imported into the public bundle. It is available through the loopback development URI and proxies to the internal backend. Replay creation uses a dark XNYS-backed calendar, defaults to the latest completed equity session, and disables closed, incomplete, and future days from server-provided status. Trading-day step controls and calendar-month controls have separate labels. Its searchable keyboard-accessible stock combobox queries only the selected date's private historical universe, groups symbols as Forming that day, Discovery candidates, and All scanned, and offers manual entry only when no universe was recorded. It never receives outcomes or future performance for selection. Pick random case samples the same eligible symbols without ranking or revealing a reason. The normal equity session is summarized as 08:30–10:00 CT, with explicit controls behind Customize time. Start blind replay is the full-width primary action and remains disabled until date, instrument, and session values are valid.

The same private build has a **Historical baseline** tab. It shows period/config identity, coverage, separate LONG and SHORT episode counts, 3/5/10-bar direction-positive percentages with numerator and eligible denominator, insufficient-data counts, median movement/excursions, and a bounded episode table. It receives these server-calculated research DTOs only from the internal API. The public scanner navigation, bundle, and API contain no baseline route or payload.

The focused replay UI displays server-bounded 10m and 3m charts with EMA/VWAP overlays, advances one completed 3m candle without reloading, saves free-text human observations, and calls a separate explicit outcome-reveal endpoint. Axis labels, replay clock, and candle tooltip use America/Chicago with DST-aware browser formatting. Each chart separates the most recent earlier-session context from the replay date and marks the current allowed replay edge; nothing to the right is supplied as market data. MES creation currently shows the provider capability error and retains independent future session controls. Authentication is required before this private UI can be shared externally.

Equity dates closed by the XNYS exchange calendar display a dedicated Market closed panel rather than a generic server error. The panel offers the previous and next trading dates returned by the private API. Expected-open dates with missing provider candles display Replay unavailable and remain distinct from exchange closure.

Public endpoints used by the client are `/api/dashboard` and `/api/symbols/{symbol}`. Other public read-only endpoints support Discovery, Sectors, Forming, and chart views. Responses are explicit display DTOs, not ORM dumps. The API omits source membership and uploaded image identity. It returns 404 for unknown symbols, 422 for malformed symbols or unsupported chart timeframes, and 429 when rate limited. For private API boundaries and deployment requirements see [security](security.md).

Compose serves lockfile-built frontend assets through unprivileged Nginx; Vite remains the local development and browser-test server. `npm test --prefix frontend` exercises navigation and read-only flows; `npm run build --prefix frontend` verifies the production bundle. External deployment should place the built frontend behind an HTTPS reverse proxy. Image release and separate `homelab-k3s` ownership are described in [deployment](deployment.md).


Alert Foundation V1 adds a compact Recent Alerts table (latest five events), with
alert time, symbol link, FORMING LONG/SHORT, 3m price, 10m context and a sanitized
short explanation. The existing 15-second dashboard refresh updates events; no
WebSockets or external notification calls are introduced. Alert history shows up
to 200 stored events. The detector's exact reason remains private.

The 3m chart uses Lightweight Charts 5 `createSeriesMarkers`, populated only from
persisted alerts supplied by the stock API. It never derives FORMING from candles.
One marker per alert transition uses the exact completed decision-candle opening
instant: long below, short above. UTC epoch seconds avoid double timezone shifts;
axis/tooltips use America/New_York (DST-aware ET). Events without a matching visible
candle are omitted, not moved to another candle. Re-entry and direct direction
changes can produce additional markers; persistent same-direction states do not.
Known sectors excludes UNKNOWN/Unclassified and displays the count of stocks with
missing metadata. Unknown stocks remain visible and scanned.
