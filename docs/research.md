# Historical research

The configured research observation window defaults to 08:00 inclusive–10:00 exclusive in `America/Chicago`; timezone-aware conversion handles CST/CDT. It tags observations inside or outside the window. Every symbol in the active scanning universe, including setup state NONE, is recorded during the window. This supports missed-move review as well as detected-setup review.

Historical observations store the strategy version, evaluation time, trading date, context, setup state/reason, price, EMA/VWAP/volume features, candle state, decision eligibility, sector, feed/provider/session metadata, and associated discovery-source memberships. They are append-only; identical re-evaluations of the same symbol/candle/version are deduplicated. A transition from PARTIAL to COMPLETED, setup-state change, sector change, or discovery-source change creates a distinct observation even on the same candle. Source overlap is internal research data. Old records can have null source/sector/candle-state fields rather than fabricated history. Normal scanner APIs do not return these records.

Normalized persisted 3m and 10m candles permit reconstruction. An observation at T uses only candles and features known at or before T. Later market data, including after 10:00, is retained for objective outcomes. The current detector can use a partial candle and that fact is stored. Filtering by COMPLETED permits separate later analysis without rewriting detector behavior.

Nightly analysis defaults to `NIGHTLY_ANALYSIS_TIME=18:00` and `NIGHTLY_ANALYSIS_TIMEZONE=America/Chicago`. It calculates 3m forward close returns after 3, 5, and 10 candles, and favorable/adverse excursions with times to each extreme, using future candles after the observation. Results are idempotently attached to observations. NONE states retain raw price returns rather than invented trade direction. Insufficient future data leaves the relevant measurement unavailable. No WIN/LOSS label, rule promotion, LLM, ML, or trade instruction is produced. For a backfill, run `docker compose run --rm research python -m research.job --date YYYY-MM-DD`.

For observation price P, return after N candles is `(close_N - P) / P`, regardless of direction. Directional excursions require all next ten 3m candles. LONG favorable is `(future high - P) / P` and adverse is `(future low - P) / P`; SHORT favorable is `(P - future low) / P` and adverse is `(P - future high) / P`. MFE is the maximum favorable value clipped at zero; MAE is the minimum adverse value clipped at zero. Times to extrema are minutes from the observation 3m candle's opening timestamp to the candle opening timestamp containing the extreme, and are null if the corresponding excursion is zero. For NONE observations directional excursions remain null.

The internal research app supports date, symbol, strategy version, setup state, forming/non-forming, discovery source, sector, candle state, decision eligibility, and bounded limit filters. It is not mounted by public Compose. It must gain ADMIN/RESEARCHER authorization before external deployment. Current rules and proposals are similarly internal; proposed rules do not alter the scanner.

Strategy Lab is a separate private human-research workflow over a frozen one-minute replay snapshot. Unlike scanner observation history, it does not require a prior FORMING event. The replay clock and `BoundedMarketView` reconstruct 3m/10m charts as of each step; future data is available only to the explicitly revealed outcome endpoint. Human `NOT_YET`, `INTERESTING`, and `WOULD_CONSIDER_ENTRY` notes are annotations, not scanner states or trade labels. See [Strategy Lab](strategy-lab.md).

## Historical Strategy Baseline V1

**IMPLEMENTED / PRIVATE:** the baseline answers what objectively followed occurrences of the current frozen FORMING heuristic. It is not a profitability backtest. FORMING supplies no entry, stop, target, exit, trade, or WIN/LOSS definition.

The CLI accepts either `--start YYYY-MM-DD --end YYYY-MM-DD` or `--last-trading-days N`. XNYS selects completed sessions, excluding weekends, exchange holidays, current incomplete sessions, and future sessions. For each day the universe is reconstructed only from exact-date scanner observations, discovery memberships, and uploaded/active-universe history. Sources are deduplicated per symbol and retained privately. A missing universe is saved as a coverage limitation; symbols and past membership are never fabricated from later performance.

For each symbol the evaluator creates or reuses a frozen Strategy Lab replay and calls its `BoundedMarketView` calculation at completed 3-minute boundaries. The first decision time is 08:33 CT for the 08:30–08:32 candle; the final decision time is 10:00 CT for the 09:57–09:59 candle. The same aggregation, EMA/VWAP, 10m context, and frozen detector implementation used by Strategy Lab produces the stored evidence. Future data cannot enter that evidence. It is accessed later through the separate objective-movement method.

A distinct episode begins on a transition from `NONE` or the opposite FORMING direction into `FORMING_LONG` or `FORMING_SHORT`. Consecutive candles in the same FORMING state remain one episode. The episode ends at the first later evaluation with another state, or at the 10:00 boundary if it remains active. A later transition back into FORMING starts a new episode.

For episode anchor price `P`, raw return after N completed future 3m bars is `(close_N - P) / P`. The report counts positive raw returns for LONG and negative raw returns for SHORT. Directional MFE/MAE use the existing outcome service: LONG favorable uses future highs and adverse uses future lows; SHORT reverses that direction. No result is converted into a trade. Each horizon reports its own eligible denominator. For example, `59 / 88 eligible` means 59 direction-positive episodes among the 88 with enough future bars; other total episodes are shown as insufficient. Database fractions remain canonical decimals and private UI percentages use two decimal places.

Checkpoint rows are unique by symbol, market date, and exact strategy/config version. Evaluation and episode uniqueness prevents duplicate evidence. Completed symbol-days are skipped on rerun; failed or interrupted symbol-days resume using existing persisted replay candles and timestamps. Failures are recorded per symbol and do not abort the day. Processing is sequential, retries are bounded, backoff is configurable, and commits occur incrementally for Raspberry Pi memory and restart safety.

Run twenty completed sessions explicitly:

```sh
docker compose --profile tools up -d --build --force-recreate baseline
docker compose logs -f baseline
```

The tools service executes `python -m research.baseline --last-trading-days 20`. A bounded smoke/backfill can instead use `docker compose --profile tools run --rm baseline python -m research.baseline --start YYYY-MM-DD --end YYYY-MM-DD`. The nightly worker uses `BASELINE_MAX_CATCHUP_TRADING_DAYS` to find missing completed sessions after normal outcomes and process them in chronological order. It never starts the 20-day command automatically.

**BACKLOG hypotheses:** MTF Cloud Magnet and Psychological Number Magnet are unimplemented, independently testable research ideas. They do not affect FORMING V1, baseline calculations, replay charts, or stored evidence. Structured human observation tags are also unimplemented.
