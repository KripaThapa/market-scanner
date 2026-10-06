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
  value == null
    ? "Unavailable"
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
  LONG: "Explicit Long",
  SHORT: "Explicit Short",
  NO_GO: "No-Go",
};
const isLookout = (row) =>
  /^WATCHLIST_LEVEL_(LONG|SHORT|SUPPORT|RESISTANCE|NO_GO)$/.test(
    row.alert_type,
  );

export default function Alerts({ openSymbol }) {
  const [date, setDate] = useState(nyToday);
  const [filter, setFilter] = useState("ALL");
  const [rows, setRows] = useState([]);
  const [cursor, setCursor] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [sound, setSound] = useState(savedSoundPreference);
  const [ready, setReady] = useState(false);
  const [audioMessage, setAudioMessage] = useState("");
  const audio = useRef(null),
    enabled = useRef(sound),
    followingToday = useRef(true);
  const selectedDate = useRef(date);
  const paging = useRef(false);
  selectedDate.current = date;
  enabled.current = sound;

  useEffect(() => {
    let cancelled = false,
      timer,
      controller;
    let initialized = false,
      highestId = 0;
    setRows([]);
    paging.current = false;
    setCursor(null);
    setError("");
    setLoading(true);
    const poll = async () => {
      if (followingToday.current && date !== nyToday()) {
        setDate(nyToday());
        return;
      }
      controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 20000);
      try {
        // Always poll All: changing a display filter cannot replay notification IDs.
        const body = await request(
          `/api/alerts?trading_date=${date}&category=ALL`,
          { signal: controller.signal },
        );
        if (cancelled) return;
        const items = body.items.filter(
          (row) => isLookout(row) && row.trading_date === date,
        );
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
        setRows((current) => {
          const older = current.filter(
            (row) => Number(row.id) < (items.at(-1)?.id ?? 0),
          );
          return [...items, ...older];
        });
        if (!paging.current) setCursor(body.next_before_id);
        setError("");
      } catch (failure) {
        if (!cancelled)
          setError(
            "Cannot refresh lookout alerts. Showing the last available results.",
          );
      } finally {
        clearTimeout(timeout);
        if (!cancelled) {
          setLoading(false);
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
  const loadOlder = async () => {
    const requestedDate = date;
    try {
      const body = await request(
        `/api/alerts?trading_date=${date}&category=ALL&before_id=${cursor}`,
      );
      if (requestedDate !== selectedDate.current) return;
      paging.current = true;
      const items = body.items.filter(
        (row) => isLookout(row) && row.trading_date === date,
      );
      items.forEach((row) => seenLookoutIds.add(row.id));
      setRows((current) => [
        ...new Map([...current, ...items].map((row) => [row.id, row])).values(),
      ]);
      setCursor(body.next_before_id);
    } catch {
      setError("Cannot load older alerts. Please try again.");
    }
  };
  const visible = rows.filter(
    (row) =>
      filter === "ALL" ||
      (filter === "LEVEL"
        ? !["LONG", "SHORT"].includes(row.direction)
        : row.direction === filter),
  );
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
      {!loading && !visible.length && (
        <div className="empty">
          <h2>Your alert history is empty</h2>
          <p>No lookout alerts for this date and filter.</p>
        </div>
      )}
      <div className="lookout-list">
        {visible.map((row) => (
          <article className="lookout-alert" key={row.id}>
            <time dateTime={row.timestamp}>{time(row.timestamp)} ET</time>
            <h2>
              <a
                href={`/symbols/${encodeURIComponent(row.symbol)}`}
                onClick={(e) => {
                  e.preventDefault();
                  openSymbol(row.symbol);
                }}
              >
                {row.symbol}
              </a>{" "}
              —{" "}
              {["LONG", "SHORT"].includes(row.direction)
                ? `${row.direction} LOOKOUT`
                : "LOOKOUT"}
            </h2>
            <p>
              {row.level_type === "LONG"
                ? "Crossed above"
                : row.level_type === "SHORT"
                  ? "Crossed below"
                  : row.level_type === "NO_GO"
                    ? "No-Go level crossed below"
                    : `${types[row.level_type]} level reached`}
              : <strong>{money(row.trigger_level)}</strong>
            </p>
            <p>
              Observed price: <strong>{money(row.price)}</strong>{" "}
              <span className="muted">· {types[row.level_type]}</span>
            </p>
            <p className="lookout-pivots">
              Support:{" "}
              {(row.support_pivots || []).map(money).join(" / ") ||
                "Unavailable"}
              <br />
              Resistance:{" "}
              {(row.resistance_pivots || []).map(money).join(" / ") ||
                "Unavailable"}
            </p>
            <div className="lookout-plan">
              <strong>Game Plan</strong>
              <p>
                {row.game_plan ||
                  "Structured Game Plan unavailable in this historical record."}
              </p>
            </div>
            <small>Trading date: {row.trading_date}</small>
          </article>
        ))}
      </div>
      {cursor && <button onClick={loadOlder}>Load older alerts</button>}
    </section>
  );
}
