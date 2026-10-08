import React, { useEffect, useRef, useState } from "react";
import { request } from "./api";
import {
  seenLookoutIds,
  savedSoundPreference,
  saveSoundPreference,
  unlockAudio,
  notificationTone,
} from "./lookoutSound";

export const nyToday = () =>
  new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(
    new Date(),
  );
const money = (value) =>
  value == null || !Number.isFinite(Number(value))
    ? "—"
    : `$${Number(value).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 8 })}`;
const time = (value) =>
  new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
const types = {
  SUPPORT: "Support",
  RESISTANCE: "Resistance",
  LONG: "LONG LOOKOUT",
  SHORT: "SHORT LOOKOUT",
  NO_GO: "No-Go",
};
const isLookout = (row) =>
  /^WATCHLIST_LEVEL_(LONG|SHORT|SUPPORT|RESISTANCE|NO_GO)$/.test(
    row.alert_type,
  );

export default function Alerts() {
  const [date, setDate] = useState(nyToday);
  const [filter, setFilter] = useState("ALL");
  const [rows, setRows] = useState([]);
  const [expanded, setExpanded] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [sound, setSound] = useState(savedSoundPreference);
  const [ready, setReady] = useState(false);
  const [audioMessage, setAudioMessage] = useState("");
  const audio = useRef(null),
    enabled = useRef(sound),
    followingToday = useRef(true);
  enabled.current = sound;

  useEffect(() => {
    let cancelled = false,
      timer,
      controller;
    let initialized = false,
      highestId = 0;
    const cached = new Map();
    setRows([]);
    setExpanded(null);
    setError("");
    setLoading(true);
    const poll = async () => {
      if (followingToday.current && date !== nyToday()) {
        setDate(nyToday());
        return;
      }
      setRefreshing(true);
      controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 20000);
      try {
        // Always poll All: changing a display filter cannot replay notification IDs.
        const collected = new Map();
        let before = null;
        for (let page = 0; ; page++) {
          if (page === 20) throw new Error("History exceeds safe page limit");
          const body = await request(
            `/api/alerts?trading_date=${date}&category=ALL&limit=200${before ? `&before_id=${before}` : ""}`,
            { signal: controller.signal },
          );
          if (cancelled) return;
          const overlap = body.items.some((row) => cached.has(String(row.id)));
          body.items.forEach((row) => {
            if (isLookout(row) && row.trading_date === date)
              collected.set(String(row.id), row);
          });
          if (!body.next_before_id || overlap) break;
          if (before && Number(body.next_before_id) >= Number(before))
            throw new Error("Invalid history cursor");
          before = body.next_before_id;
        }
        const items = [...collected.values()];
        const fresh = items.some(
          (row) => Number(row.id) > highestId && !seenLookoutIds.has(row.id),
        );
        if (initialized && date === nyToday() && fresh && enabled.current) {
          if (!notificationTone(audio.current)) {
            setReady(false);
            setAudioMessage(
              "Audio needs a browser gesture. Enable audio in this tab; visual alerts remain active.",
            );
          }
        }
        items.forEach((row) => seenLookoutIds.add(row.id));
        highestId = Math.max(highestId, ...items.map((row) => Number(row.id)));
        initialized = true;
        collected.forEach((row, id) => cached.set(id, row));
        setRows([...cached.values()]);
        setError("");
      } catch (failure) {
        if (!cancelled)
          setError(
            "Cannot load complete lookout history. Showing the last complete results, if available; counts may be stale. Please retry or select another date.",
          );
      } finally {
        clearTimeout(timeout);
        if (!cancelled) {
          setLoading(false);
          setRefreshing(false);
          timer = setTimeout(poll, 15000);
        }
      }
    };
    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
      controller?.abort();
    };
  }, [date]);

  useEffect(
    () => () => {
      audio.current?.close().catch(() => {});
    },
    [],
  );

  const enableAudio = async () => {
    try {
      audio.current = await unlockAudio(audio.current);
      setReady(true);
      setSound(true);
      saveSoundPreference(true);
      setAudioMessage("");
    } catch {
      setReady(false);
      setSound(false);
      saveSoundPreference(false);
      setAudioMessage(
        "Sound is unavailable in this browser. Visual alerts remain active.",
      );
    }
  };
  const toggleSound = async () => {
    if (sound) {
      setSound(false);
      saveSoundPreference(false);
      setAudioMessage("");
      return;
    }
    await enableAudio();
  };
  const visible = rows.filter(
    (row) =>
      filter === "ALL" ||
      (filter === "LEVEL"
        ? !["LONG", "SHORT"].includes(row.direction)
        : row.direction === filter),
  );
  const groups = [
    ...visible
      .reduce((map, row) => {
        const key = `${row.trading_date}:${row.symbol}`;
        if (!map.has(key))
          map.set(key, { key, symbol: row.symbol, events: [] });
        map.get(key).events.push(row);
        return map;
      }, new Map())
      .values(),
  ];
  const newestFirst = (a, b) =>
    (Date.parse(b.timestamp) || 0) - (Date.parse(a.timestamp) || 0) ||
    Number(b.id) - Number(a.id);
  groups.forEach((group) => group.events.sort(newestFirst));
  groups.sort((a, b) => newestFirst(a.events[0], b.events[0]));
  const visibleKeys = groups.map((group) => group.key).join("|");
  useEffect(() => {
    if (expanded && !visibleKeys.split("|").includes(expanded))
      setExpanded(null);
  }, [visibleKeys, expanded]);
  const trigger = (row) =>
    `${types[row.level_type] || "—"} ${money(row.trigger_level)}`;
  const eventTime = (row) =>
    row.timestamp && Number.isFinite(Date.parse(row.timestamp))
      ? `${time(row.timestamp)} ET`
      : "—";
  return (
    <section className="lookout-alerts" aria-label="Watchlist Lookout alerts">
      <div className="lookout-controls">
        <label>
          Alerts date
          <input
            aria-label="Alerts date"
            type="date"
            value={date}
            max={nyToday()}
            onChange={(e) => {
              if (!e.target.value) return;
              followingToday.current = e.target.value === nyToday();
              setDate(e.target.value);
            }}
          />
        </label>
        <button aria-pressed={sound} onClick={toggleSound}>
          Sound {sound ? "On" : "Off"}
        </button>
        {sound && (
          <small className="sound-indicator">
            ● Sound enabled{!ready && " · browser gesture needed"}
          </small>
        )}
        {sound && !ready && (
          <button onClick={enableAudio}>Enable audio in this tab</button>
        )}
        <span>Auto-refresh · 15s · ET</span>
      </div>
      <div className="lookout-filters" role="group" aria-label="Alert category">
        {[
          ["ALL", "All"],
          ["LONG", "Long"],
          ["SHORT", "Short"],
          ["LEVEL", "Levels"],
        ].map(([key, label]) => (
          <button
            key={key}
            aria-pressed={filter === key}
            onClick={() => setFilter(key)}
          >
            {label}
          </button>
        ))}
      </div>
      <p className="muted">
        Watchlist Lookout alerts call attention to supplied levels. They are not
        trade recommendations.
      </p>
      {date !== nyToday() && (
        <p className="notice">
          Historical alerts · sound is disabled for this date.
        </p>
      )}
      {audioMessage && <p role="status">{audioMessage}</p>}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {loading && <p role="status">Loading lookout alerts…</p>}
      {refreshing && !loading && <small role="status">Refreshing…</small>}
      {!loading && !error && !groups.length && (
        <p className="muted">
          {filter === "ALL"
            ? "No lookout alerts for this date."
            : `No ${filter === "LEVEL" ? "Levels" : filter === "LONG" ? "Long" : "Short"} lookout alerts for this date.`}
        </p>
      )}
      <div className="lookout-list">
        {groups.map(({ key, symbol, events }) => {
          const latest = events[0];
          const open = expanded === key;
          const plan = events.find((event) => event.game_plan)?.game_plan;
          const panelId = `history-${key}`;
          return (
            <article className="lookout-group" key={key}>
              <button
                className="lookout-row"
                aria-expanded={open}
                aria-controls={panelId}
                onClick={() => setExpanded(open ? null : key)}
              >
                <strong>{symbol}</strong>
                <span className="lookout-summary">
                  {trigger(latest)} · {eventTime(latest)}
                </span>
                <span
                  className="lookout-count"
                  aria-label={`${events.length} persisted alerts`}
                >
                  {events.length}
                </span>
                <span aria-hidden="true">{open ? "⌃" : "⌄"}</span>
              </button>
              {open && (
                <div id={panelId} className="lookout-details">
                  <h3>Trigger history</h3>
                  <div className="lookout-table-scroll">
                    <table
                      className="lookout-history"
                      aria-label={`${symbol} trigger history`}
                    >
                      <thead>
                        <tr>
                          <th>Time</th>
                          <th>Trigger</th>
                          <th>Observed price</th>
                        </tr>
                      </thead>
                      <tbody>
                        {events.map((event) => (
                          <tr key={event.id}>
                            <td>{eventTime(event)}</td>
                            <td>{trigger(event)}</td>
                            <td>{money(event.price)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="lookout-plan">
                    <h3>Original Game Plan</h3>
                    <p className={plan ? "" : "muted"}>
                      {plan || "Original Game Plan unavailable."}
                    </p>
                  </div>
                </div>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
