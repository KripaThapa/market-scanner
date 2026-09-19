import React, { useEffect, useMemo, useState } from "react";
import { request } from "./api";

const monthKey = (value) => value.slice(0, 7);
const monthParts = (key) => key.split("-").map(Number);
const shiftMonth = (key, amount) => {
  const [year, month] = monthParts(key);
  const shifted = new Date(Date.UTC(year, month - 1 + amount, 1));
  return `${shifted.getUTCFullYear()}-${String(shifted.getUTCMonth() + 1).padStart(2, "0")}`;
};
const longDate = (value) =>
  new Intl.DateTimeFormat("en-US", {
    weekday: "long",
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${value}T12:00:00Z`));

export default function CalendarPicker({ value, onChange }) {
  const today = new Date().toISOString().slice(0, 7);
  const [month, setMonth] = useState(value ? monthKey(value) : today);
  const [calendar, setCalendar] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    const [year, monthNumber] = monthParts(month);
    request(
      `/api/internal/strategy-lab/calendar?year=${year}&month=${monthNumber}`,
    )
      .then((data) => {
        if (!active) return;
        setCalendar(data);
        setError("");
        if (!value) {
          onChange(data.default_date);
          if (monthKey(data.default_date) !== month)
            setMonth(monthKey(data.default_date));
        }
      })
      .catch((failure) => active && setError(failure.message));
    return () => {
      active = false;
    };
  }, [month, value, onChange]);

  const offset = useMemo(() => {
    const [year, monthNumber] = monthParts(month);
    return new Date(Date.UTC(year, monthNumber - 1, 1)).getUTCDay();
  }, [month]);
  const adjacent = async (direction) => {
    const data = await request(
      `/api/internal/strategy-lab/calendar/adjacent?date=${value}&direction=${direction}`,
    );
    onChange(data.date);
    setMonth(monthKey(data.date));
  };
  const nextAllowed = calendar && value && value < calendar.default_date;

  return (
    <section className="calendar-picker" aria-label="Trading day">
      <span className="calendar-control-label">Trading day</span>
      <div className="date-stepper">
        <button
          type="button"
          onClick={() => adjacent("previous")}
          disabled={!value}
          aria-label="Previous trading day"
        >
          ‹
        </button>
        <strong>{value ? longDate(value) : "Loading trading day…"}</strong>
        <button
          type="button"
          onClick={() => adjacent("next")}
          disabled={!nextAllowed}
          aria-label="Next trading day"
        >
          ›
        </button>
      </div>
      <span className="calendar-control-label">Calendar month</span>
      <div className="calendar-head">
        <button
          type="button"
          onClick={() => setMonth(shiftMonth(month, -1))}
          aria-label="Previous month"
        >
          ←
        </button>
        <strong>
          {new Intl.DateTimeFormat("en-US", {
            month: "long",
            year: "numeric",
            timeZone: "UTC",
          }).format(new Date(`${month}-01T12:00:00Z`))}
        </strong>
        <button
          type="button"
          onClick={() => setMonth(shiftMonth(month, 1))}
          aria-label="Next month"
        >
          →
        </button>
      </div>
      <div className="calendar-grid week-labels">
        {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((day) => (
          <span key={day}>{day}</span>
        ))}
      </div>
      <div className="calendar-grid">
        {Array.from({ length: offset }, (_, index) => (
          <span key={`blank-${index}`} />
        ))}
        {calendar?.days.map((day) => (
          <button
            type="button"
            key={day.date}
            disabled={day.status !== "OPEN"}
            className={`${day.status.toLowerCase()} ${value === day.date ? "selected" : ""}`}
            title={day.reason?.replaceAll("_", " ") || "US equity trading day"}
            onClick={() => onChange(day.date)}
          >
            {Number(day.date.slice(-2))}
          </button>
        ))}
      </div>
      {error && <p className="field-error">{error}</p>}
      <small>Unavailable dates are closed, incomplete, or in the future.</small>
    </section>
  );
}
