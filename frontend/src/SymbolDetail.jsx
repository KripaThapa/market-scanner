import React, { useEffect, useRef, useState } from "react";
import { CandlestickSeries, ColorType, createChart } from "lightweight-charts";
import { request } from "./api";
import { Badge, Panel, time } from "./components";

const nyTime = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});
const formatTime = (seconds) => nyTime.format(new Date(seconds * 1000));
const value = (number) => (number == null ? "—" : Number(number).toFixed(3));
function CandleChart({ title, candles }) {
  const node = useRef(null);
  const [hover, setHover] = useState(null);
  useEffect(() => {
    if (!node.current || !candles.length) return;
    const chart = createChart(node.current, {
      width: node.current.clientWidth,
      height: 360,
      layout: {
        background: { type: ColorType.Solid, color: "#101923" },
        textColor: "#a8b8ca",
      },
      grid: {
        vertLines: { color: "#1b2936" },
        horzLines: { color: "#1b2936" },
      },
      rightPriceScale: { borderColor: "#354457" },
      timeScale: {
        borderColor: "#354457",
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: formatTime,
      },
      localization: { timeFormatter: formatTime },
    });
    const bars = candles.map((candle) => ({
      ...candle,
      time: Math.floor(Date.parse(candle.timestamp) / 1000),
    }));
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#54d7a7",
      downColor: "#f38388",
      wickUpColor: "#54d7a7",
      wickDownColor: "#f38388",
      borderVisible: false,
    });
    series.setData(
      bars.map(({ time: barTime, open, high, low, close }) => ({
        time: barTime,
        open,
        high,
        low,
        close,
      })),
    );
    chart.subscribeCrosshairMove((event) => {
      if (!event.time) return setHover(null);
      const candle = bars.find((bar) => bar.time === event.time);
      setHover(candle || null);
    });
    chart.timeScale().fitContent();
    const resize = new ResizeObserver(() => {
      if (node.current) chart.applyOptions({ width: node.current.clientWidth });
    });
    resize.observe(node.current);
    return () => {
      resize.disconnect();
      chart.remove();
    };
  }, [candles]);
  return (
    <Panel title={title} subtitle="Scanner-persisted market candles">
      {candles.length ? (
        <>
          <div
            ref={node}
            className="candle-chart"
            role="img"
            aria-label={`${title} candlestick chart`}
          />
          <div className="chart-hover" aria-live="off">
            {hover ? (
              <>
                <strong>{formatTime(hover.time)} ET</strong>
                <span>
                  O {value(hover.open)} · H {value(hover.high)} · L{" "}
                  {value(hover.low)} · C {value(hover.close)}
                </span>
                <span>Volume {Math.round(hover.volume).toLocaleString()}</span>
              </>
            ) : (
              "Hover a candle for its timestamp, OHLC and volume. Drag to pan; scroll to zoom."
            )}
          </div>
        </>
      ) : (
        <p className="chart-empty">
          No scanner candle data is available for this timeframe yet.
        </p>
      )}
      <div className="chart-attribution">
        Charts by{" "}
        <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">
          TradingView
        </a>{" "}
        Lightweight Charts™
      </div>
    </Panel>
  );
}

export default function SymbolDetail({ symbol, onBack, scanUpdated }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    request(`/api/symbols/${encodeURIComponent(symbol)}`, {
      signal: controller.signal,
    })
      .then((body) => {
        setDetail(body);
        setError("");
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setError(failure.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [symbol, scanUpdated]);
  return (
    <>
      <button className="text-button detail-back" onClick={onBack}>
        ← Forming Setups
      </button>
      {loading && (
        <div className="notice" role="status">
          Loading scanner chart data…
        </div>
      )}
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {detail && (
        <>
          <div className="detail-summary">
            <div>
              <span>Setup state</span>
              <strong>{detail.setup_state}</strong>
            </div>
            <div>
              <span>10-minute context</span>
              <Badge value={detail.context_10m} />
            </div>
            <div>
              <span>3-minute context</span>
              <Badge value={detail.context_3m} />
            </div>
            <div>
              <span>3-minute candle</span>
              <strong>{detail.candle_state || "UNAVAILABLE"}</strong>
            </div>
            <div>
              <span>First detected</span>
              <strong>
                {detail.first_detected_at
                  ? time(detail.first_detected_at)
                  : "—"}
              </strong>
            </div>
            <div>
              <span>Last updated</span>
              <strong>
                {detail.last_seen_at ? time(detail.last_seen_at) : "—"}
              </strong>
            </div>
          </div>
          <CandleChart title="10-minute context" candles={detail.candles_10m} />
          <CandleChart title="3-minute price" candles={detail.candles_3m} />
        </>
      )}
    </>
  );
}
