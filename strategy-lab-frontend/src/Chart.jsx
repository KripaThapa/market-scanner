import React, { useEffect, useMemo, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  LineSeries,
  createSeriesMarkers,
  createChart,
} from "lightweight-charts";

import EmaCloud from "./EmaCloud";

const EMPTY = [];
const colors = {
  ema_5: "#4dd6a8",
  ema_12: "#62a8ff",
  ema_34: "#f0b65b",
  ema_50: "#d77df0",
  vwap: "#e7e9ed",
};
const reviewColors = {
  ema_5: "#70b9a9",
  ema_12: "#52897e",
  ema_34: "#8ca4cc",
  ema_50: "#627699",
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
  markers = EMPTY,
  levels = EMPTY,
  review = false,
  onEventSelect,
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
      height: review && title.startsWith("3 MIN") ? 410 : 300,
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
      ...(review && levels.length
        ? {
            autoscaleInfoProvider: (original) => {
              const info = original();
              if (!info) return info;
              return {
                ...info,
                priceRange: {
                  minValue: Math.min(
                    info.priceRange.minValue,
                    ...levels.map((l) => l.price),
                  ),
                  maxValue: Math.max(
                    info.priceRange.maxValue,
                    ...levels.map((l) => l.price),
                  ),
                },
              };
            },
          }
        : {}),
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
    const visibleMarkers = review
      ? markers.filter((m) => m.chart_time)
      : markers;
    const mappedMarkers = visibleMarkers
      .map((marker) => {
        const state = marker.type || marker.state;
        const long = state.endsWith("LONG");
        const level = state.startsWith("WATCHLIST_LEVEL");
        return {
          id: marker.id,
          time: Math.floor(
            Date.parse(review ? marker.chart_time : marker.timestamp) / 1000,
          ),
          position: long ? "belowBar" : "aboveBar",
          color: level ? "#e8bb70" : long ? "#57c9ac" : "#eb9298",
          shape: level ? "circle" : long ? "arrowUp" : "arrowDown",
          text: review
            ? `${level ? "LEVEL" : "FORMING"} ${long ? "LONG" : "SHORT"} · ${chartTime(Math.floor(Date.parse(marker.timestamp) / 1000), timezone)}`
            : state,
        };
      })
      .sort((a, b) => a.time - b.time);
    createSeriesMarkers(bars, mappedMarkers);
    if (review) {
      bars.attachPrimitive(
        new EmaCloud(normalized, "ema_5", "ema_12", "rgba(77,214,168,0.10)"),
      );
      bars.attachPrimitive(
        new EmaCloud(normalized, "ema_34", "ema_50", "rgba(98,168,255,0.09)"),
      );
      for (const level of levels)
        bars.createPriceLine({
          price: level.price,
          color: "#d9b779",
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: true,
          title: `${level.direction} $${Number(level.price).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 8 })} · supplied`,
        });
      chart.subscribeClick((param) => {
        const event =
          visibleMarkers.find((m) => m.id === param.hoveredObjectId) ||
          visibleMarkers.find(
            (m) =>
              Math.floor(Date.parse(m.chart_time) / 1000) ===
              Number(param.time),
          );
        if (event && onEventSelect) onEventSelect(event.id);
      });
    }
    for (const field of Object.keys(colors)) {
      const line = chart.addSeries(LineSeries, {
        color: (review ? reviewColors : colors)[field],
        lineWidth: review
          ? field === "vwap"
            ? 2
            : 1
          : field === "vwap"
            ? 1
            : 2,
        lineStyle: review && field === "vwap" ? 2 : 0,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      line.setData(
        normalized.map((row) =>
          row[field] == null
            ? { time: row.time }
            : { time: row.time, value: row[field] },
        ),
      );
    }
    chart.timeScale().fitContent();

    const placeGuides = () => {
      if (review) return;
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
      tooltip.current.innerHTML = `<strong>${when.date} · ${when.time} ${timezone === "America/New_York" ? "ET" : "CT"}</strong>
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
  }, [
    candles,
    markers,
    levels,
    review,
    onEventSelect,
    replayTime,
    sessionStart,
    timezone,
    title,
  ]);

  return (
    <section className="chart-card">
      <header>
        <h2>{title}</h2>
        <span>
          {timezone} · {timezone === "America/New_York" ? "ET" : "CT"}
        </span>
      </header>
      {candles.length ? (
        <div className="chart-wrap">
          <div ref={node} aria-label={`${title} candlestick chart`} />
          {!review && (
            <>
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
                  {chartTime(
                    Math.floor(Date.parse(replayTime) / 1000),
                    timezone,
                  )}{" "}
                  CT
                </span>
              </div>
            </>
          )}
          <div ref={tooltip} className="chart-tooltip" role="tooltip" hidden />
        </div>
      ) : (
        <p>
          {review
            ? "No stored candles available for this timeframe."
            : "No visible completed candles yet."}
        </p>
      )}
      <footer>
        {!review && (
          <>
            <span>Previous session</span>
            <span className="session-key">│ Current replay session</span>
          </>
        )}
        {review && (
          <span>Drag to pan · Scroll to zoom · Click an event candle</span>
        )}
        {Object.entries(review ? reviewColors : colors).map(([key, color]) => (
          <span key={key} style={{ color }}>
            {key.replace("_", " ").toUpperCase()}
          </span>
        ))}
      </footer>
    </section>
  );
}
