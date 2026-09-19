import React, { useEffect, useMemo, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  LineSeries,
  createSeriesMarkers,
  createChart,
} from "lightweight-charts";

const colors = {
  ema_5: "#4dd6a8",
  ema_12: "#62a8ff",
  ema_34: "#f0b65b",
  ema_50: "#d77df0",
  vwap: "#e7e9ed",
};
const formatter = (timezone, options) =>
  new Intl.DateTimeFormat("en-US", { timeZone: timezone, ...options });
const chartTime = (unix, timezone) =>
  formatter(timezone, {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(unix * 1000));
const tooltipTime = (unix, timezone) => ({
  date: formatter(timezone, {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(unix * 1000)),
  time: chartTime(unix, timezone),
});
const display = (value) =>
  value == null
    ? "—"
    : Number(value).toLocaleString("en-US", { maximumFractionDigits: 4 });

export default function Chart({
  title,
  candles,
  timezone,
  sessionStart,
  replayTime,
  markers = [],
}) {
  const node = useRef(null);
  const tooltip = useRef(null);
  const sessionLine = useRef(null);
  const replayEdge = useRef(null);
  const replayDate = useMemo(
    () =>
      sessionStart
        ? formatter(timezone, { month: "short", day: "numeric" }).format(
            new Date(sessionStart),
          )
        : "Replay",
    [sessionStart, timezone],
  );

  useEffect(() => {
    if (!node.current || !candles.length) return;
    const chart = createChart(node.current, {
      width: node.current.clientWidth,
      height: 300,
      layout: {
        background: { type: ColorType.Solid, color: "#111821" },
        textColor: "#aebac7",
      },
      localization: {
        timeFormatter: (time) => chartTime(Number(time), timezone),
      },
      grid: {
        vertLines: { color: "#202a36" },
        horzLines: { color: "#202a36" },
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: (time) => chartTime(Number(time), timezone),
      },
    });
    const normalized = candles.map((row) => ({
      ...row,
      time: Math.floor(Date.parse(row.timestamp) / 1000),
    }));
    const byTime = new Map(normalized.map((row) => [row.time, row]));
    const bars = chart.addSeries(CandlestickSeries, {
      upColor: "#42cf9b",
      downColor: "#ef7880",
      borderVisible: false,
      wickUpColor: "#42cf9b",
      wickDownColor: "#ef7880",
    });
    bars.setData(
      normalized.map(({ time, open, high, low, close }) => ({
        time,
        open,
        high,
        low,
        close,
      })),
    );
    createSeriesMarkers(
      bars,
      markers.map((marker) => ({
        time: Math.floor(Date.parse(marker.timestamp) / 1000),
        position: marker.state === "FORMING_LONG" ? "belowBar" : "aboveBar",
        color: marker.state === "FORMING_LONG" ? "#42cf9b" : "#ef7880",
        shape: marker.state === "FORMING_LONG" ? "arrowUp" : "arrowDown",
        text: marker.state,
      })),
    );
    for (const field of Object.keys(colors)) {
      const line = chart.addSeries(LineSeries, {
        color: colors[field],
        lineWidth: field === "vwap" ? 1 : 2,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      line.setData(
        normalized
          .filter((row) => row[field] != null)
          .map((row) => ({ time: row.time, value: row[field] })),
      );
    }
    chart.timeScale().fitContent();

    const placeGuides = () => {
      const start = Math.floor(Date.parse(sessionStart) / 1000);
      const startX = chart.timeScale().timeToCoordinate(start);
      const edgeX = chart
        .timeScale()
        .timeToCoordinate(normalized[normalized.length - 1].time);
      if (sessionLine.current && startX != null)
        sessionLine.current.style.left = `${startX}px`;
      if (replayEdge.current && edgeX != null)
        replayEdge.current.style.left = `${edgeX}px`;
    };
    requestAnimationFrame(placeGuides);
    chart.timeScale().subscribeVisibleTimeRangeChange(placeGuides);

    chart.subscribeCrosshairMove((param) => {
      if (!tooltip.current) return;
      const row = param.time == null ? null : byTime.get(Number(param.time));
      if (!row || !param.point) {
        tooltip.current.hidden = true;
        return;
      }
      const when = tooltipTime(row.time, timezone);
      tooltip.current.hidden = false;
      tooltip.current.style.left = `${Math.min(param.point.x + 12, node.current.clientWidth - 190)}px`;
      tooltip.current.style.top = `${Math.max(param.point.y - 82, 8)}px`;
      tooltip.current.innerHTML = `<strong>${when.date} · ${when.time} CT</strong>
        <span>O ${display(row.open)} · H ${display(row.high)}</span>
        <span>L ${display(row.low)} · C ${display(row.close)}</span>
        <span>Volume ${display(row.volume)}</span>
        <span>EMA 5 ${display(row.ema_5)} · EMA 12 ${display(row.ema_12)}</span>
        <span>EMA 34 ${display(row.ema_34)} · EMA 50 ${display(row.ema_50)}</span>
        <span>VWAP ${display(row.vwap)}</span>`;
    });

    const resize = new ResizeObserver(() => {
      if (node.current) {
        chart.applyOptions({ width: node.current.clientWidth });
        placeGuides();
      }
    });
    resize.observe(node.current);
    return () => {
      resize.disconnect();
      chart.timeScale().unsubscribeVisibleTimeRangeChange(placeGuides);
      chart.remove();
    };
  }, [candles, markers, replayTime, sessionStart, timezone]);

  return (
    <section className="chart-card">
      <header>
        <h2>{title}</h2>
        <span>America/Chicago · CT</span>
      </header>
      {candles.length ? (
        <div className="chart-wrap">
          <div ref={node} aria-label={`${title} candlestick chart`} />
          <div
            ref={sessionLine}
            className="session-divider"
            data-testid={`${title}-session-divider`}
          >
            <span>{replayDate} · REPLAY</span>
          </div>
          <div
            ref={replayEdge}
            className="replay-edge"
            data-testid={`${title}-replay-edge`}
          >
            <span>
              NOW ·{" "}
              {chartTime(Math.floor(Date.parse(replayTime) / 1000), timezone)}{" "}
              CT
            </span>
          </div>
          <div ref={tooltip} className="chart-tooltip" role="tooltip" hidden />
        </div>
      ) : (
        <p>No visible completed candles yet.</p>
      )}
      <footer>
        <span>Previous session</span>
        <span className="session-key">│ Current replay session</span>
        {Object.entries(colors).map(([key, color]) => (
          <span key={key} style={{ color }}>
            {key.replace("_", " ").toUpperCase()}
          </span>
        ))}
      </footer>
    </section>
  );
}
