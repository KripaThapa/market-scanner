import React, { useEffect, useState } from "react";
import { request } from "./api";
import Chart from "./Chart";
import CalendarPicker from "./CalendarPicker";
import StockSelector from "./StockSelector";
import BaselineReport from "./BaselineReport";

const localTime = (value, zone) =>
  value
    ? new Intl.DateTimeFormat("en-US", {
        timeZone: zone,
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }).format(new Date(value))
    : "—";

export default function App() {
  const [view, setView] = useState("REPLAY");
  const [instrument, setInstrument] = useState(""),
    [assetType, setAssetType] = useState("EQUITY");
  const [date, setDate] = useState(""),
    [start, setStart] = useState("08:30"),
    [end, setEnd] = useState("10:00");
  const [customTime, setCustomTime] = useState(false),
    [universe, setUniverse] = useState(null),
    [capabilities, setCapabilities] = useState(null);
  const [replay, setReplay] = useState(null),
    [decision, setDecision] = useState("NOT_YET"),
    [reason, setReason] = useState("");
  const [error, setError] = useState(null),
    [outcome, setOutcome] = useState(null),
    [busy, setBusy] = useState(false);
  const call = async (action) => {
    setBusy(true);
    try {
      const value = await action();
      setError(null);
      return value;
    } catch (failure) {
      setError(failure.details || { message: failure.message });
    } finally {
      setBusy(false);
    }
  };
  const create = async (event) => {
    event.preventDefault();
    const value = await call(() =>
      request("/api/internal/replays", {
        method: "POST",
        body: JSON.stringify({
          instrument,
          asset_type: assetType,
          market_date: date,
          start,
          end,
          blind_mode: true,
        }),
      }),
    );
    if (value) {
      setReplay(value);
      setOutcome(null);
    }
  };
  const move = async (direction) => {
    const value = await call(() =>
      request(`/api/internal/replays/${replay.id}/${direction}`, {
        method: "POST",
      }),
    );
    if (value) setReplay(value);
  };
  const save = async () => {
    const value = await call(() =>
      request(`/api/internal/replays/${replay.id}/observations`, {
        method: "POST",
        body: JSON.stringify({ decision, reason }),
      }),
    );
    if (value) {
      setReason("");
      setReplay(await request(`/api/internal/replays/${replay.id}`));
    }
  };
  const complete = async () => {
    const value = await call(() =>
      request(`/api/internal/replays/${replay.id}/complete`, {
        method: "POST",
      }),
    );
    if (value) setReplay(value);
  };
  const reveal = async () => {
    const value = await call(() =>
      request(`/api/internal/replays/${replay.id}/reveal`, { method: "POST" }),
    );
    if (value) {
      setOutcome(value);
      setReplay(await request(`/api/internal/replays/${replay.id}`));
    }
  };
  useEffect(() => {
    if (assetType === "FUTURE") {
      setInstrument("MES");
      setStart("08:00");
      setCustomTime(true);
    } else {
      setInstrument("");
      setStart("08:30");
      setEnd("10:00");
      setCustomTime(false);
    }
  }, [assetType]);
  useEffect(() => {
    request("/api/internal/strategy-lab/capabilities")
      .then(setCapabilities)
      .catch(() => setCapabilities(null));
  }, []);
  useEffect(() => {
    if (assetType !== "EQUITY" || !date) return;
    let active = true;
    setUniverse(null);
    setInstrument("");
    request(`/api/internal/strategy-lab/universe?date=${date}`)
      .then((data) => active && setUniverse(data))
      .catch(
        (failure) =>
          active && setError(failure.details || { message: failure.message }),
      );
    return () => {
      active = false;
    };
  }, [assetType, date]);
  const randomCase = () => {
    if (!universe?.symbols.length) return;
    const values = new Uint32Array(1);
    crypto.getRandomValues(values);
    setInstrument(universe.symbols[values[0] % universe.symbols.length]);
  };
  const validSession = Boolean(start && end && start < end);
  return (
    <main>
      <div className="private-banner">
        PRIVATE OWNER TOOL · authentication required before external exposure
      </div>
      <header className="hero">
        <div>
          <span>STRATEGY LAB V1</span>
          <h1>Historical visual replay</h1>
          <p>
            Blind candle-by-candle research. Human observations are not trading
            signals.
          </p>
        </div>
      </header>
      <nav className="lab-tabs" aria-label="Private Strategy Lab views">
        <button
          className={view === "REPLAY" ? "selected" : ""}
          onClick={() => setView("REPLAY")}
        >
          Replay
        </button>
        <button
          className={view === "BASELINE" ? "selected" : ""}
          onClick={() => setView("BASELINE")}
        >
          Historical baseline
        </button>
      </nav>
      {view === "BASELINE" && <BaselineReport />}
      {view === "REPLAY" && (
        <>
          {!replay && (
            <form className="create" onSubmit={create}>
              <div className="form-heading">
                <span>NEW BLIND REPLAY</span>
                <p>
                  Choose a historical session without seeing what happened next.
                </p>
              </div>
              <label>
                Asset
                <select
                  value={assetType}
                  onChange={(e) => setAssetType(e.target.value)}
                >
                  <option>EQUITY</option>
                  <option>FUTURE</option>
                </select>
              </label>
              {assetType === "EQUITY" ? (
                <>
                  <CalendarPicker value={date} onChange={setDate} />
                  <StockSelector
                    universe={universe}
                    value={instrument}
                    onChange={setInstrument}
                  />
                  {universe?.recorded && (
                    <button
                      type="button"
                      className="secondary"
                      onClick={randomCase}
                    >
                      Pick random case
                    </button>
                  )}
                  <section className="session-choice">
                    <div>
                      <span>Session</span>
                      <strong>Morning research · 8:30 AM–10:00 AM CT</strong>
                    </div>
                    <button
                      type="button"
                      className="text-button"
                      onClick={() => setCustomTime(!customTime)}
                    >
                      {customTime ? "Use default" : "Customize time"}
                    </button>
                  </section>
                </>
              ) : (
                <>
                  <label>
                    Instrument
                    <input value="MES" disabled />
                  </label>
                  <label>
                    Date
                    <input
                      type="date"
                      value={date}
                      onChange={(e) => setDate(e.target.value)}
                    />
                  </label>
                  <div className="capability-note">
                    {capabilities?.asset_types?.FUTURE?.limitation ||
                      "MES futures replay requires a compatible historical-data provider."}
                  </div>
                </>
              )}
              {(customTime || assetType === "FUTURE") && (
                <div className="time-fields">
                  <label>
                    Replay start
                    <input
                      type="time"
                      value={start}
                      onChange={(e) => setStart(e.target.value)}
                    />
                  </label>
                  <label>
                    Replay end
                    <input
                      type="time"
                      value={end}
                      onChange={(e) => setEnd(e.target.value)}
                    />
                  </label>
                </div>
              )}
              <button
                className="start-replay"
                disabled={busy || !date || !instrument || !validSession}
              >
                Start blind replay
              </button>
            </form>
          )}
          {error && (
            <section className="error" role="alert">
              <h2>
                {error.error === "MARKET_CLOSED"
                  ? "Market closed"
                  : "Replay unavailable"}
              </h2>
              <p>{error.message}</p>
              {error.error === "MARKET_CLOSED" && (
                <div className="controls">
                  <button
                    type="button"
                    onClick={() => {
                      setDate(error.previous_trading_day);
                      setError(null);
                    }}
                  >
                    Previous trading day
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setDate(error.next_trading_day);
                      setError(null);
                    }}
                  >
                    Next trading day
                  </button>
                </div>
              )}
            </section>
          )}
          {replay && (
            <>
              <section className="summary">
                <div>
                  <span>Instrument</span>
                  <strong>{replay.instrument}</strong>
                </div>
                <div>
                  <span>Replay time</span>
                  <strong>
                    {localTime(replay.current_replay_time, replay.timezone)} CT
                  </strong>
                </div>
                <div>
                  <span>10m context</span>
                  <strong>{replay.context_10m}</strong>
                </div>
                <div>
                  <span>3m state</span>
                  <strong>{replay.state_3m}</strong>
                </div>
                <div>
                  <span>Mode</span>
                  <strong>{replay.blind_mode ? "BLIND" : "REVEALED"}</strong>
                </div>
              </section>
              <Chart
                title="10-minute context"
                candles={replay.candles_10m}
                timezone={replay.timezone}
                sessionStart={replay.visible_start}
                replayTime={replay.current_replay_time}
              />
              <Chart
                title="3-minute setup research"
                candles={replay.candles_3m}
                timezone={replay.timezone}
                sessionStart={replay.visible_start}
                replayTime={replay.current_replay_time}
                markers={replay.forming_markers}
              />
              <div className="controls">
                <button onClick={() => move("previous")} disabled={busy}>
                  Previous candle
                </button>
                <button onClick={() => move("next")} disabled={busy}>
                  Next candle
                </button>
              </div>
              <section className="observation">
                <h2>Your observation</h2>
                <div className="decisions">
                  {["NOT_YET", "INTERESTING", "WOULD_CONSIDER_ENTRY"].map(
                    (item) => (
                      <button
                        className={decision === item ? "selected" : ""}
                        onClick={() => setDecision(item)}
                        key={item}
                      >
                        {item.replaceAll("_", " ")}
                      </button>
                    ),
                  )}
                </div>
                <label>
                  Why?
                  <textarea
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    maxLength={4000}
                  />
                </label>
                <button onClick={save} disabled={busy || !reason.trim()}>
                  Save observation
                </button>
                <ul>
                  {replay.observations.map((item) => (
                    <li key={item.id}>
                      <strong>
                        {localTime(item.replay_time, replay.timezone)} ·{" "}
                        {item.decision.replaceAll("_", " ")}
                      </strong>
                      <p>{item.free_text_reason}</p>
                    </li>
                  ))}
                </ul>
              </section>
              <div className="controls">
                <button onClick={complete} disabled={busy}>
                  Complete replay
                </button>
                <button onClick={reveal} disabled={busy}>
                  Reveal outcome
                </button>
              </div>
              {outcome && (
                <section className="outcome">
                  <h2>{outcome.label}</h2>
                  <p>
                    Objective movement after each observation. This is not a
                    trade return, win, loss, or profit.
                  </p>
                  {outcome.items.map((item) => (
                    <pre key={item.observation.id}>
                      {JSON.stringify(item, null, 2)}
                    </pre>
                  ))}
                </section>
              )}
              <button
                className="new"
                onClick={() => {
                  setReplay(null);
                  setOutcome(null);
                }}
              >
                Start another replay
              </button>
            </>
          )}
        </>
      )}
    </main>
  );
}
