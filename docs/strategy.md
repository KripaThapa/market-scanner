# Current strategy status

The **10-minute timeframe determines market context/trend**. The **3-minute
timeframe will eventually determine entry**. Currently, the 3-minute section
reports the same trend classifier and an experimental forming observation.
It does not produce an entry decision or trade signal.

## Implemented signals

- **EMA 5/12:** fast cloud, calculated from candle closes.
- **EMA 34/50:** slow cloud, calculated from candle closes.
- **Session VWAP:** cumulative typical-price times volume divided by cumulative
  volume, reset each local trading date and computed separately per timeframe.

The existing classifier labels a candle BULLISH when EMA 5 > EMA 12,
EMA 34 > EMA 50, and close is strictly above VWAP and all four EMAs. It labels
BEARISH when both EMA comparisons are reversed and close is strictly below VWAP
and all four EMAs. Otherwise the trend is MIXED.

The printed cloud labels use BULLISH for a strict greater-than comparison and
BEARISH otherwise, including equality. The printed VWAP position uses ABOVE
for close > VWAP and BELOW otherwise, including equality. These display labels
are preserved from the prototype; equality does not satisfy the corresponding
strict bearish trend condition.

## Future / TBD — not implemented

All of the following remain undefined and unimplemented:

- A+, A, and A- grading
- EMA 5/12 curl detection
- Relative strength
- Sector strength
- Key levels
- PMH/PDL logic
- News/catalyst analysis
- Options flow
- Alert qualification rules and real alert delivery
- 3-minute entry rules and their relationship to 10-minute context

No grading criteria or entry triggers are specified for these future features.
There is no trading or order execution functionality.

Screenshot ingestion extracts ticker symbols only. Image notes, price levels,
long/short labels, setups, and annotations remain future/TBD and do not influence
context classification or define strategy rules.

## Experimental Forming Setup V1

The current strategy identifier is `experimental-forming-v1/<configuration hash>`.
The suffix derives from the four configured V1 thresholds; historical
observations retain the identifier that produced them. A future algorithm change
must use a new base version. The private internal rules API and Strategy Lab Rules
tab read implemented checks and experimental thresholds from backend configuration.
Proposed rules remain internal research hypotheses and never alter this detector.

This is an **EXPERIMENTAL scanner heuristic**, not an official Ripster A+, A,
or A- rule. The 10-minute classifier supplies directional context only. The
3-minute candles determine whether a pullback is developing. Only the latest
3-minute close is evaluated; the preceding configured number of 3-minute bars
provides the prior move. No entry or alert is generated.

| Scanner environment variable | Experimental default | Meaning |
| --- | ---: | --- |
| `FORMING_LOOKBACK_BARS` | 6 | Prior 3-minute bars, excluding current; minimum 2 |
| `FORMING_MIN_RETRACE_PCT` | 0.003 | Minimum retrace fraction, 0.3% |
| `FORMING_CLOUD_PROXIMITY_PCT` | 0.004 | Maximum distance from 5/12 cloud divided by current close, 0.4% |
| `FORMING_SLOW_TOLERANCE_PCT` | 0.002 | Allowed penetration beyond protective 34/50 edge, 0.2% |

These initial values are experimental because the project requirements do not
specify numerical thresholds. The fractions must be in `[0, 1)` and lookback
must be at least 2. Invalid configuration fails the scan cycle.

For `FORMING_LONG`, 10-minute context must be `BULLISH`. Let `P` be latest
3-minute close and `H` the maximum high of the preceding lookback bars. Require
`(H-P)/H >= min_retrace_pct`, 3-minute `EMA34 > EMA50`, and
`P >= min(EMA34, EMA50) * (1-slow_tolerance_pct)`.

For `FORMING_SHORT`, 10-minute context must be `BEARISH`. Let `L` be the
minimum low of the preceding lookback bars. Require
`(P-L)/L >= min_retrace_pct`, 3-minute `EMA34 < EMA50`, and
`P <= max(EMA34, EMA50) * (1+slow_tolerance_pct)`.

Both directions require current price within the configured distance of the
3-minute EMA 5/12 cloud. The cloud spans the lesser and greater EMA. Distance
is zero inside it; otherwise the gap to the nearest edge divided by `P`.
Nonfinite values, nonpositive price, missing bars, or missing directional context
produce `NONE`.

A setup is active only while every condition remains true on each scan. Failure
of any condition marks the record inactive and removes it from the active list;
history is retained. A later qualifying scan creates a new record. Future
near-entry, triggered, and invalidated states are reserved, not implemented.

Limitations: the prior high/low can be a noisy move; no minimum preceding move
is required. Existing live aggregation includes a partial latest candle and now
retains provider-supplied extended-hours equity bars rather than applying an
exchange calendar. Outside available provider hours it may scan stale bars.
No 5/12 curl, relative strength, news, options
flow, grading, or execution criteria are included. OCR confidence and symbol
validation remain ingestion heuristics.

## Dashboard and worker boundaries

The PostgreSQL scanner worker reuses the same calculations and classifier as the
standalone CLI. Containerization, daily snapshots, queued uploads, per-ticker
error handling, and UI polling introduce no strategy changes. `PENDING` and
`NO DATA` are operational states, not trend classifications. A failed ticker is
never silently labeled MIXED.

Sector tables count active-universe symbols and existing 10-minute context
labels. Discovery and sector data do not influence Forming Setup V1 or define
sector strength. Volatility and relative-strength
metrics remain null/TBD. The forming table stores V1 observations. Alert
generation, qualification, grading, and delivery remain unimplemented.

Any future strategy implementation must update this document in the same change,
clearly distinguishing Implemented, Experimental, and TBD rules. Assumptions must
not be presented as defined Ripster strategy information.

Historical collection observes every symbol, including `NONE`, during the 8–10 AM
Central research window. A separate nightly job measures raw future returns and
excursions using later candles; it never modifies the deterministic scanner.
See [research history](research.md). Future ML/Transformer and LLM research are
planned but not implemented.

Strategy Lab reuses this equity classifier and Experimental Forming Setup V1 only for time-bounded equity replay annotations. It does not change thresholds or strategy behavior. The current provider cannot replay MES, and the equity forming heuristic is not claimed or applied as a MES rule. Human replay decisions create research notes only. See [Strategy Lab](strategy-lab.md).

Historical Strategy Baseline V1 also calls this same frozen classifier through Strategy Lab's bounded replay service. It records state at completed 3-minute boundaries and measures later objective movement around distinct FORMING episodes. It does not define an entry or win rate and does not alter any threshold. MTF Cloud Magnet and Psychological Number Magnet remain unimplemented future research hypotheses and have no effect on current calculations.
