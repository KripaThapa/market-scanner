import { test, expect } from "@playwright/test";
import { alertMarkers } from "../src/alertMarkers";

test("persisted events align to exact decision candles across ET daylight and standard time", () => {
  const candles = [
    { timestamp: "2026-09-18T09:42:00-04:00" },
    { timestamp: "2026-12-18T09:42:00-05:00" },
  ];
  const long = {
    id: 1,
    alert_type: "FORMING_LONG",
    timestamp: "2026-09-18T13:46:00Z",
    decision_candle_at: "2026-09-18T13:42:00Z",
  };
  const short = {
    id: 2,
    alert_type: "FORMING_SHORT",
    timestamp: "2026-12-18T14:46:00Z",
    decision_candle_at: "2026-12-18T14:42:00Z",
  };
  const markers = alertMarkers(
    [
      short,
      long,
      long,
      { ...long, id: 3, decision_candle_at: "2026-09-18T13:41:00Z" },
    ],
    candles,
  );
  expect(markers).toHaveLength(2);
  expect(markers[0]).toMatchObject({
    time: Date.parse(candles[0].timestamp) / 1000,
    position: "belowBar",
    text: "FORMING LONG",
  });
  expect(markers[1]).toMatchObject({
    time: Date.parse(candles[1].timestamp) / 1000,
    position: "aboveBar",
    text: "FORMING SHORT",
  });
  expect(alertMarkers([], candles)).toEqual([]);
});
