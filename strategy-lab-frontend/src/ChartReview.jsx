import React, { useCallback, useEffect, useState } from "react";
import { request } from "./api";
import Chart from "./Chart";

export const percentage = (value) =>
  value == null || !Number.isFinite(Number(value))
    ? "Unavailable"
    : new Intl.NumberFormat("en-US", {
        style: "percent",
        maximumFractionDigits: 2,
        signDisplay: "exceptZero",
      }).format(value);
const price = (value) =>
  value == null
    ? "Unavailable"
    : `$${Number(value).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;
const when = (value) =>
  new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
const name = (event) =>
  event.type.replace("WATCHLIST_LEVEL", "LEVEL").replaceAll("_", " ");
const today = () =>
  new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(
    new Date(),
  );

export default function ChartReview() {
  const [date, setDate] = useState(today),
    [symbols, setSymbols] = useState([]),
    [symbol, setSymbol] = useState("");
  const [data, setData] = useState(null),
    [selected, setSelected] = useState(null),
    [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    let active = true;
    setSymbols([]);
    setSymbol("");
    setData(null);
    setSelected(null);
    setError("");
    if (!date) {
      setLoading(false);
      return;
    }
    setLoading(true);
    request(`/api/internal/strategy-lab/review/watchlist?date=${date}`)
      .then((value) => {
        if (active) {
          setSymbols(value.symbols);
          setSymbol(value.symbols[0] || "");
        }
      })
      .catch((e) => active && setError(e.message))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [date]);
  useEffect(() => {
    let active = true;
    setData(null);
    setSelected(null);
    setError("");
    if (!symbol || !date) return;
    setLoading(true);
    request(
      `/api/internal/strategy-lab/review/chart?date=${date}&symbol=${encodeURIComponent(symbol)}`,
    )
      .then((value) => {
        if (active) setData(value);
      })
      .catch((e) => active && setError(e.message))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [date, symbol]);
  const selectEvent = useCallback((id) => setSelected(id), []);
  const event = data?.events.find((item) => item.id === selected);
  return (
    <section className="chart-review" aria-label="Daily watchlist chart review">
      <div className="review-controls">
        <label>
          Watchlist date
          <input
            type="date"
            value={date}
            max={today()}
            onChange={(e) => setDate(e.target.value)}
          />
        </label>
        <label>
          Watchlist stock
          <select
            value={symbol}
            disabled={!symbols.length}
            onChange={(e) => setSymbol(e.target.value)}
          >
            {!symbols.length && <option value="">No uploaded watchlist</option>}
            {symbols.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <p>
          {symbols.length
            ? `${symbols.length} stocks · one review per symbol`
            : "Choose a date with an uploaded watchlist."}
        </p>
      </div>
      {error && (
        <p role="alert" className="field-error">
          {error}
        </p>
      )}
      {loading && <p role="status">Loading stored chart history…</p>}
      {!loading && !symbols.length && !error && (
        <div className="review-empty">
          No uploaded watchlist stored for this date.
        </div>
      )}
      {data && (
        <>
          <div className="review-heading">
            <div>
              <h2>{data.symbol}</h2>
              <p>
                {data.date} · {data.event_basis}
              </p>
            </div>
            <span>Historical review · ET</span>
          </div>
          {data.legacy_date && (
            <p className="review-note">
              Legacy upload date in New York; the original ingestion trading
              date was not recorded.
            </p>
          )}
          <div className="review-layout">
            <div className="review-charts">
              <Chart
                title="10 MIN — MARKET STRUCTURE"
                candles={data.candles_10m}
                timezone={data.timezone}
                levels={data.levels}
                review
              />
              <Chart
                title="3 MIN — SETUP"
                candles={data.candles_3m}
                timezone={data.timezone}
                markers={data.events}
                levels={data.levels}
                review
                onEventSelect={selectEvent}
              />
              <div className="review-legend">
                <span>↗ / ↘ FORMING episode</span>
                <span>● LEVEL crossing</span>
                <span>┄ Supplied watchlist level</span>
              </div>
              {data.levels.length > 0 && (
                <p className="review-levels">
                  Supplied levels:{" "}
                  {data.levels
                    .map((level) => `${level.direction} ${price(level.price)}`)
                    .join(" · ")}
                </p>
              )}
              <p className="review-note">{data.chart_note}</p>
            </div>
            <aside className="review-details" aria-label="Event review">
              <h3>Scanner events</h3>
              <p className="review-note">
                Select a chart marker or an event below.
              </p>
              {!data.events.length && (
                <p>No persisted events for this symbol and date.</p>
              )}
              <div className="review-events">
                {data.events.map((item) => (
                  <button
                    key={item.id}
                    aria-pressed={selected === item.id}
                    onClick={() => setSelected(item.id)}
                    className={
                      item.type.startsWith("WATCHLIST")
                        ? "level-event"
                        : "forming-event"
                    }
                  >
                    <strong>{name(item)}</strong>
                    <time>{when(item.timestamp)}</time>
                  </button>
                ))}
              </div>
              {event ? (
                <>
                  <section className="event-detail">
                    <h3>
                      {event.type.startsWith("WATCHLIST")
                        ? `${event.type.endsWith("LONG") ? "LONG" : "SHORT"} LEVEL CROSSED`
                        : name(event)}
                    </h3>
                    <p>
                      {when(event.timestamp)} ET · {event.origin}
                    </p>
                    {!event.chart_time && (
                      <p className="review-note">
                        The matching candle is unavailable; no marker was placed
                        on another candle.
                      </p>
                    )}
                    <dl>
                      <div>
                        <dt>
                          {event.type.startsWith("WATCHLIST")
                            ? "Cross price"
                            : "Alert price"}
                        </dt>
                        <dd>{price(event.price)}</dd>
                      </div>
                      {event.trigger_level != null ? (
                        <div>
                          <dt>Watchlist level</dt>
                          <dd>{price(event.trigger_level)}</dd>
                        </div>
                      ) : (
                        <>
                          <div>
                            <dt>10m context</dt>
                            <dd>
                              {event.context_10m?.toLowerCase() ||
                                "Unavailable"}
                            </dd>
                          </div>
                          <div>
                            <dt>VWAP position</dt>
                            <dd>
                              {event.vwap_position?.toLowerCase() ||
                                "Unavailable"}
                            </dd>
                          </div>
                        </>
                      )}
                    </dl>
                  </section>
                  <section className="review-outcome">
                    <h3>What happened after?</h3>
                    <p className="review-note">
                      Retrospective research only. Price movement is not a trade
                      return or recommendation.
                    </p>
                    <p className="review-note">
                      Later prices show raw price change; best and adverse moves
                      are relative to the alert direction.
                    </p>
                    <dl>
                      <div>
                        <dt>Alert price</dt>
                        <dd>{price(event.price)}</dd>
                      </div>
                      {[9, 15, 30].map((minutes) => (
                        <div key={minutes}>
                          <dt>{minutes} min later</dt>
                          <dd>
                            {percentage(event.outcome?.returns?.[minutes])}
                          </dd>
                        </div>
                      ))}
                      <div>
                        <dt>Best move afterward</dt>
                        <dd>{percentage(event.outcome?.best_move)}</dd>
                      </div>
                      <div>
                        <dt>Largest move against alert</dt>
                        <dd>{percentage(event.outcome?.adverse_move)}</dd>
                      </div>
                    </dl>
                    {event.outcome?.window ? (
                      <p className="review-note">
                        {event.outcome.window.label}
                        <br />
                        {when(event.outcome.window.start)}–
                        {when(event.outcome.window.end)} ET
                      </p>
                    ) : (
                      <p className="review-note">
                        Exact outcomes are unavailable where compatible
                        persisted measurements are missing.
                      </p>
                    )}
                  </section>
                </>
              ) : (
                <p className="review-note">
                  Event-time details and outcomes appear here after selection.
                </p>
              )}
            </aside>
          </div>
        </>
      )}
    </section>
  );
}
