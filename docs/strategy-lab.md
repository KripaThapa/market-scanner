# Strategy Lab V1

## Status and purpose

**IMPLEMENTED:** Strategy Lab is a private owner research application for blind, visual, candle-by-candle replay. It records human observations. It is not the public scanner, a trading strategy, a backtester, or an order system. The public React bundle and public FastAPI app contain no Strategy Lab routes or data.

**IMPLEMENTED:** Replays are instrument-neutral (`Instrument(symbol, asset_type, provider_identifier)`) with `EQUITY` and `FUTURE` domain values. Equity replay is operational. MES is the first intended futures instrument, but MES replay is **not operational** with the current provider. The configured Alpaca/IEX client supplies stocks; Alpaca's documented historical clients cover stocks, crypto, and options, with no futures client. V1 rejects MES creation with HTTP 422 rather than substituting another product or fabricating candles.

**TBD:** MES requires a provider with historical one-minute futures OHLCV, explicit contract identity and roll metadata, futures exchange/session rules, timestamps, historical/live availability, and a defined futures VWAP reset. No vendor or paid account was added.

## Market-day validation

**IMPLEMENTED for equities:** replay creation validates the selected date against the XNYS calendar supplied by `exchange-calendars` before requesting provider data or inserting a replay. Saturdays, Sundays, and exchange holidays return the structured `MARKET_CLOSED` condition with the selected date, `US_EQUITY`, closure reason, and adjacent trading dates. The private UI presents this as a normal “Market closed” message with previous/next trading-day actions.

The replay form uses a private server-backed month calendar. The backend labels each date `OPEN`, `CLOSED`, or `UNAVAILABLE`; React only renders those results. Closed sessions, incomplete current sessions, and future dates cannot be selected. The initial selection is the most recent completed XNYS trading session rather than the browser's current date. Previous/next controls also obtain exchange sessions from the backend.

`MARKET_CLOSED` is distinct from `NO_DATA`. `NO_DATA` means the calendar expected an equity session but the configured provider returned no usable normalized candles. Calendar validation is asset-specific and is not applied to futures; futures calendar semantics remain TBD with the future provider.

## Replay clock and no look-ahead

At session creation the historical provider supplies normalized one-minute opening-timestamp candles for a warm-up interval, visible interval, and ten later 3m bars. The one-minute snapshot is persisted with the replay for reproducibility. It is not sent wholesale to the browser.

Every active calculation receives `BoundedMarketView(source, as_of=T)`. That type makes available only source bars whose opening timestamp is strictly before T, meaning the one-minute candle opening at 08:05 is first usable at 08:06. Indicators, aggregation, context, equity forming evaluation, markers, and chart DTOs are built from that bounded copy. No caller receives the unbounded frame. Chart DTOs include the comparable replay-time window from the most recent earlier market-data date as visual context, followed by current-session candles strictly before the replay clock. Other warm-up bars remain hidden. Future outcome measurements use a separate, explicitly gated service method and endpoint.

Replay advances on three-minute boundaries. With opening timestamps:

- Replay time 08:03 contains the completed 08:00 3m candle, sourced from 08:00, 08:01, and 08:02 one-minute bars.
- Replay time 08:06 adds the 08:03 3m candle, sourced from 08:03–08:05.
- Ten-minute buckets open 08:00, 08:10, 08:20, etc. At replay time 08:06, the displayed 08:00 10m candle is partial and contains only 08:00–08:05. It cannot contain 08:06–08:09.

Pandas resampling is day-aligned (`origin=start_day`, existing 30-minute offset). The offset preserves the documented 00/03/06 3m alignment and 00/10/20 10m alignment. Replay time, storage, and API timestamps are timezone-aware. The normal equity replay form defaults to 08:30 inclusive–10:00 America/Chicago; the user can expand “Customize time” for another bounded interval. The generic/futures default remains 08:00–10:00 and is not derived from the equity preset. Tests cover CDT and existing research-window tests cover CST/CDT conversion.

## Sessions, warm-up, VWAP and strategy annotations

**IMPLEMENTED for equities:** Alpaca/IEX one-minute history is requested without the former 09:30–15:59 New York filter. Provider-supplied extended-hours bars are retained, so 08:00–08:30 Central is no longer intentionally discarded. IEX is one exchange and may differ from consolidated SIP data; unavailable bars are not fabricated. The live scanner and replay use provider-returned bars, and timestamp semantics are candle start.

EMA 5/12/34/50 warm-up defaults to seven calendar days (`REPLAY_WARMUP_CALENDAR_DAYS`, allowed 1–30). Warm-up contributes to indicators but is omitted before the requested visible start and cannot create visible research decisions. Existing EMA formulas are unchanged.

Existing VWAP groups the calculated candles by the source market timezone's calendar date and resets at midnight America/New_York. Replay preserves that definition and records it in each session. This is explicit experimental equity behavior; it is not a claim about official exchange VWAP. **TBD:** a futures VWAP session/reset must be defined with a future MES provider and is not invented here.

For equities only, the existing Experimental Forming Setup V1 may annotate the replay from bounded provider-neutral candles. A marker appears only at the replay step where FORMING first becomes known. Strategy Lab observations do not alter that detector. MES forming evaluation is disabled; a future raw MES replay should begin with price/indicators/context only until futures applicability is explicitly decided.

## Persistence and human workflow

Migration 0007 adds `strategy_replay_sessions`, `strategy_replay_candles`, and `strategy_replay_observations`. A replay stores instrument, asset type, market date, visible bounds, current clock, provider/feed, session configuration, status (`CREATED`, `IN_PROGRESS`, `COMPLETED`), blind/reveal state, and a frozen one-minute source snapshot. Human observations store the exact replay time, observed price, strategy version when applicable, one of `NOT_YET`, `INTERESTING`, or `WOULD_CONSIDER_ENTRY`, and required free text.

The private UI presents 10m and 3m candlesticks with EMA 5/12/34/50 and VWAP, previous/next controls, three neutral research decisions, and an unstructured “Why?” field. Both charts render their axes and hover details in America/Chicago, matching the replay header. A restrained divider labels the current replay-session start, and a `NOW` guide labels the rightmost candle available at the current replay step. Hover details contain CT date/time, OHLCV, and available EMA/VWAP values; missing indicators render as unavailable without suppressing the candle. No prompting checkboxes bias the researcher. Multiple observations can be saved. These records create no rule, trade, order, entry, stop, or target.

The private **Historical baseline** tab summarizes the frozen detector across an explicitly run date range. It uses the same replay clock and bounded market view as interactive replay, aggregates consecutive FORMING candles into distinct episodes, shows per-horizon numerator/eligible denominator/insufficient counts, and provides an episode drilldown. It does not call those proportions win rates. The baseline CLI is restartable and is deliberately absent from normal container startup.

For equity creation, the searchable stock combobox uses only records whose `trading_date` equals the selected day. It combines historical scanner observations, discovery memberships, and persisted active-universe membership. Navigation groups are `Forming that day`, `Discovery candidates`, and `All scanned`; each symbol appears once and the groups are research navigation rather than rankings. The response contains symbols and group membership only, with no outcomes, returns, MFE/MAE, source provenance, or future-day universe. If that date has no recorded universe, the form says so and offers validated manual symbol entry. “Pick random case” samples uniformly from that same date-bound symbol set using browser cryptographic randomness; it does not query or weight outcome data and does not disclose a selection reason.

Blind mode returns no outcomes, future bars, later annotations, MFE, MAE, or result labels. Completing a replay does not reveal outcomes. An explicit Reveal Outcome action is required. The separate outcome response is labeled `POST-OBSERVATION MARKET MOVEMENT` and reports raw 3/5/10-bar close returns plus maximum up/down price movement. It does not report WIN, LOSS, profit, or trade return.

## Private routes and deployment

The untrusted public app has no replay route. The internal app provides `/api/internal/strategy-lab/capabilities`, private calendar/month and adjacent-session metadata, the date-bound historical universe, replay create/list/get, next/previous/seek, 3m/10m chart, observation create/list, complete, reveal, and gated outcome endpoints. Docker runs `internal-backend` only on the private Compose network. The private frontend is loopback-bound at `http://127.0.0.1:${STRATEGY_LAB_PORT:-3003}`. It is not authenticated; do not expose it externally. Add mature authentication and ADMIN/RESEARCHER authorization before any external deployment.

## Backlog boundary

**BACKLOG/TBD:** deterministic entries, exits, stops, targets, position sizing, WIN/LOSS, R multiples, futures tick/point/contract calculations, contract rolling, automated backtesting, optimization, ML/AI rule generation, brokerage integration, and stock ranking. A future backtester can reuse `BoundedMarketView`, the replay clock, persisted source snapshot, and frozen strategy version without weakening the as-of boundary.

MTF Cloud Magnet and Psychological Number Magnet are **BACKLOG research hypotheses only**. Neither is implemented in the strategy, baseline evaluator, chart visualization, or human-observation model.
