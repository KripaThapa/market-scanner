import React, { useEffect, useState } from "react";
import { request } from "./api";

export default function DailyWatchlist() {
  const [today, setToday] = useState(null);
  const [pending, setPending] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    const result = await request("/api/internal/strategy-lab/watchlist/today");
    setToday(result);
  };

  useEffect(() => {
    refresh().catch((failure) => setError(failure.message));
  }, []);

  const upload = async (event) => {
    event.preventDefault();
    const file = event.currentTarget.elements.screenshot.files[0];
    if (!file) return;
    setBusy(true);
    setError("");
    setPending(null);
    const body = new FormData();
    body.append("file", file);
    try {
      const result = await request(
        "/api/internal/strategy-lab/watchlist/upload",
        { method: "POST", body },
      );
      setPending(result);
    } catch (failure) {
      const detail = failure.details;
      setError(detail?.report?.message || detail?.message || failure.message);
      if (detail?.report) setPending(detail.report);
    } finally {
      setBusy(false);
    }
  };

  const activate = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await request(
        "/api/internal/strategy-lab/watchlist/activate",
        {
          method: "POST",
          body: JSON.stringify({ snapshot_id: pending.snapshot_id }),
        },
      );
      setToday({ date: result.active.date, active: result.active });
      setPending(null);
    } catch (failure) {
      setError(failure.details?.message || failure.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      className="daily-watchlist"
      aria-labelledby="daily-watchlist-title"
    >
      <header>
        <h2 id="daily-watchlist-title">Daily Watchlist</h2>
        <p>Today: {today?.date || "Loading…"}</p>
      </header>

      {today?.active && (
        <div className="daily-watchlist-active" role="status">
          <strong>
            Today&apos;s watchlist is active — {today.active.validated_count}{" "}
            symbols
          </strong>
          <p>It will be included on the scanner&apos;s next normal cycle.</p>
          <p>Symbols: {today.active.symbols.join(", ")}</p>
        </div>
      )}

      <form className="daily-watchlist-upload" onSubmit={upload}>
        <label>
          Upload Screenshot
          <input
            name="screenshot"
            type="file"
            accept="image/png,image/jpeg"
            required
          />
        </label>
        <button type="submit" disabled={busy}>
          {busy ? "Processing…" : "Upload Screenshot"}
        </button>
      </form>

      {error && (
        <p className="daily-watchlist-error" role="alert">
          {error}
        </p>
      )}

      {pending && (
        <section
          className="daily-watchlist-review"
          aria-labelledby="extracted-title"
        >
          <h3 id="extracted-title">Extracted Watchlist</h3>
          <p>Review the validated symbols before activation.</p>
          {pending.validated_symbols?.length ? (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Original Note</th>
                  </tr>
                </thead>
                <tbody>
                  {pending.validated_symbols.map((symbol) => (
                    <tr key={symbol}>
                      <td>{symbol}</td>
                      <td>Not captured by the current screenshot extractor</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p>No validated symbols were extracted.</p>
          )}
          {!!pending.rejection_details?.length && (
            <div className="daily-watchlist-error" role="status">
              <strong>Some screenshot text could not be used:</strong>
              <ul>
                {pending.rejection_details.map((item, index) => (
                  <li key={`${item.candidate}-${index}`}>
                    {item.candidate}: {item.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <button
            type="button"
            onClick={activate}
            disabled={busy || !pending.validated_symbols?.length}
          >
            Confirm &amp; Activate Watchlist
          </button>
        </section>
      )}
    </section>
  );
}
