// Only persisted events whose exact decision candle is visible are charted.
// Epoch seconds identify instants; ET formatting belongs to the chart axis.
export function alertMarkers(alerts, candles) {
  const seconds = (stamp) => Date.parse(stamp) / 1000;
  const visible = new Set(candles.map((candle) => seconds(candle.timestamp)));
  const seen = new Set();
  return alerts
    .flatMap((alert) => {
      const time = seconds(alert.decision_candle_at);
      if (
        !visible.has(time) ||
        seen.has(alert.id) ||
        !["FORMING_LONG", "FORMING_SHORT"].includes(alert.alert_type)
      )
        return [];
      seen.add(alert.id);
      const long = alert.alert_type === "FORMING_LONG";
      return [
        {
          id: String(alert.id),
          time,
          position: long ? "belowBar" : "aboveBar",
          color: long ? "#54d7a7" : "#f38388",
          shape: long ? "arrowUp" : "arrowDown",
          text: long ? "FORMING LONG" : "FORMING SHORT",
        },
      ];
    })
    .sort((left, right) => left.time - right.time);
}
