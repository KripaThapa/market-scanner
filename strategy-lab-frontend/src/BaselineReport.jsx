import React, { useEffect, useState } from "react";
import { request } from "./api";

const percent = (value) =>
  value == null ? "—" : `${value > 0 ? "+" : ""}${Number(value).toFixed(2)}%`;

function Direction({ title, report, favorable }) {
  const metric = (label, value) => (
    <div className="baseline-metric">
      <span>{label}</span>
      <strong>
        {value.percentage == null ? "—" : `${value.percentage.toFixed(1)}%`}
      </strong>
      <small>
        {value.numerator} / {value.denominator} eligible · {value.insufficient}{" "}
        insufficient
      </small>
    </div>
  );
  return (
    <section className="baseline-direction">
      <h2>{title}</h2>
      <p>{report.episodes} distinct episodes</p>
      <div className="baseline-grid">
        {metric(`3 bars ${favorable}`, report.bars_3)}
        {metric(`5 bars ${favorable}`, report.bars_5)}
        {metric(`10 bars ${favorable}`, report.bars_10)}
        <div className="baseline-metric">
          <span>Median 3-bar move</span>
          <strong>{percent(report.bars_3.median_percent)}</strong>
        </div>
        <div className="baseline-metric">
          <span>Median 5-bar move</span>
          <strong>{percent(report.bars_5.median_percent)}</strong>
        </div>
        <div className="baseline-metric">
          <span>Median 10-bar move</span>
          <strong>{percent(report.bars_10.median_percent)}</strong>
        </div>
        <div className="baseline-metric">
          <span>Median favorable excursion</span>
          <strong>{percent(report.median_favorable_excursion_percent)}</strong>
        </div>
        <div className="baseline-metric">
          <span>Median adverse excursion</span>
          <strong>{percent(report.median_adverse_excursion_percent)}</strong>
        </div>
      </div>
    </section>
  );
}

export default function BaselineReport() {
  const [report, setReport] = useState(null);
  const [episodes, setEpisodes] = useState([]);
  const [error, setError] = useState("");
  const [symbols, setSymbols] = useState("");
  const [sessionCount, setSessionCount] = useState(20);
  const [submitting, setSubmitting] = useState(false);
  const [selectedRunId, setSelectedRunId] = useState(null);
  const load = async (runId = null) => {
    const path = runId
      ? `/api/internal/strategy-lab/baseline?run_id=${runId}`
      : "/api/internal/strategy-lab/baseline";
    const value = await request(path);
    setReport(value);
    setSelectedRunId(value.id ?? null);
    if (value.id) {
      const details = await request(
        `/api/internal/strategy-lab/baseline/episodes?run_id=${value.id}`,
      );
      setEpisodes(details.items);
    } else {
      setEpisodes([]);
    }
    return value;
  };
  useEffect(() => {
    load().catch((failure) => setError(failure.message));
  }, []);
  useEffect(() => {
    if (!selectedRunId || report?.status !== "IN_PROGRESS") return undefined;
    const timer = window.setInterval(() => {
      load(selectedRunId).catch((failure) => setError(failure.message));
    }, 2000);
    return () => window.clearInterval(timer);
  }, [selectedRunId, report?.status]);
  const submitFixed = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const response = await request(
        "/api/internal/strategy-lab/baseline/fixed-universe",
        {
          method: "POST",
          body: JSON.stringify({
            symbols: symbols.split(/[\s,]+/).filter(Boolean),
            last_trading_days: Number(sessionCount),
          }),
        },
      );
      await load(response.id);
    } catch (failure) {
      setError(failure.message);
    } finally {
      setSubmitting(false);
    }
  };
  if (error) return <section className="error">{error}</section>;
  if (!report) return <p>Loading historical baseline…</p>;
  if (report.status === "NOT_RUN")
    return (
      <div className="baseline-report">
        <section className="baseline-empty">
          <h2>Historical Strategy Baseline</h2>
          <p>No baseline run has been recorded yet.</p>
        </section>
        <form className="fixed-research-form" onSubmit={submitFixed}>
          <h2>Fixed research universe</h2>
          <p>Fixed research universe — historical what-if analysis.</p>
          <label>
            Symbols (comma or space separated)
            <textarea
              value={symbols}
              onChange={(event) => setSymbols(event.target.value)}
              placeholder="NVDA, AMD, TSLA, AAPL"
              rows={3}
              required
            />
          </label>
          <label>
            Previous completed XNYS sessions
            <input
              type="number"
              min="1"
              max="250"
              value={sessionCount}
              onChange={(event) => setSessionCount(event.target.value)}
            />
          </label>
          <button type="submit" disabled={submitting}>
            {submitting ? "Starting…" : "Run fixed-universe analysis"}
          </button>
        </form>
      </div>
    );
  const requested =
    report.coverage.trading_sessions_requested ?? report.coverage.trading_days;
  const covered = report.coverage.sessions_with_universe_coverage ?? 0;
  const missing = report.coverage.sessions_missing_universe ?? 0;
  const noUniverse = requested > 0 && missing === requested;
  return (
    <div className="baseline-report">
      <header>
        <span>PRIVATE RESEARCH</span>
        <h1>Historical Strategy Baseline</h1>
        <p>
          Objective movement after frozen FORMING episodes. These statistics are
          not a win rate.
        </p>
      </header>
      <form className="fixed-research-form" onSubmit={submitFixed}>
        <h2>Fixed research universe</h2>
        <p>Fixed research universe — historical what-if analysis.</p>
        <label>
          Symbols (comma or space separated)
          <textarea
            value={symbols}
            onChange={(event) => setSymbols(event.target.value)}
            placeholder="NVDA, AMD, TSLA, AAPL"
            rows={3}
            required
          />
        </label>
        <label>
          Previous completed XNYS sessions
          <input
            type="number"
            min="1"
            max="250"
            value={sessionCount}
            onChange={(event) => setSessionCount(event.target.value)}
          />
        </label>
        <button type="submit" disabled={submitting}>
          {submitting ? "Starting…" : "Run fixed-universe analysis"}
        </button>
      </form>
      {report.run_type === "FIXED_RESEARCH_UNIVERSE" && (
        <section className="fixed-research-notice">
          <h2>Fixed research universe — historical what-if analysis.</h2>
          <p>
            These selected symbols are not evidence of what the scanner
            historically discovered or traded.
          </p>
          <p>
            Research universe: {(report.research_universe || []).join(", ")}
          </p>
          <p>
            Symbol-days attempted: {report.coverage.symbol_days_attempted} ·
            successfully evaluated: {report.coverage.symbols_evaluated} ·
            provider NO_DATA: {report.coverage.provider_no_data} · failures:{" "}
            {report.coverage.symbol_failures}
          </p>
        </section>
      )}
      {missing > 0 && (
        <section className="baseline-coverage-warning" role="alert">
          <h2>
            {noUniverse
              ? "Historical universe unavailable"
              : "Historical universe coverage incomplete"}
          </h2>
          <p>
            {noUniverse
              ? "This run does not contain sufficient historical universe coverage for strategy evaluation. No symbols were known to the recorded scanner universe during the requested sessions."
              : `${missing} of ${requested} requested trading sessions have no recorded historical universe. Results cover only sessions with recorded membership.`}
          </p>
        </section>
      )}
      <section className="baseline-summary">
        {report.run_type && (
          <div>
            <span>Run type</span>
            <strong>{report.run_type}</strong>
          </div>
        )}
        <div>
          <span>Period</span>
          <strong>
            {report.period.start} – {report.period.end}
          </strong>
        </div>
        <div>
          <span>Strategy</span>
          <strong>{report.strategy_version}</strong>
        </div>
        <div>
          <span>Sessions requested</span>
          <strong>{requested}</strong>
        </div>
        <div>
          <span>Sessions processed</span>
          <strong>
            {report.coverage.trading_sessions_processed ??
              report.coverage.trading_days_completed}
          </strong>
        </div>
        {report.run_type !== "FIXED_RESEARCH_UNIVERSE" && (
          <div>
            <span>Sessions with universe</span>
            <strong>{covered}</strong>
          </div>
        )}
        {report.run_type !== "FIXED_RESEARCH_UNIVERSE" && (
          <div>
            <span>Sessions missing universe</span>
            <strong>{missing}</strong>
          </div>
        )}
        <div>
          <span>Symbols evaluated</span>
          <strong>{report.coverage.symbols_evaluated}</strong>
        </div>
        <div>
          <span>Eligible evaluations</span>
          <strong>{report.coverage.eligible_evaluations}</strong>
        </div>
        <div>
          <span>Failures</span>
          <strong>{report.coverage.symbol_failures}</strong>
        </div>
      </section>
      <Direction
        title="FORMING LONG"
        report={report.forming_long}
        favorable="positive"
      />
      <Direction
        title="FORMING SHORT"
        report={report.forming_short}
        favorable="negative"
      />
      <section className="episode-list">
        <h2>Episode drilldown</h2>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Date</th>
                <th>Direction</th>
                <th>Price</th>
                <th>3 bars</th>
                <th>5 bars</th>
                <th>10 bars</th>
                <th>MFE</th>
                <th>MAE</th>
              </tr>
            </thead>
            <tbody>
              {episodes.map((item) => (
                <tr key={item.id}>
                  <td>{item.symbol}</td>
                  <td>{item.market_date}</td>
                  <td>{item.setup_state.replace("FORMING_", "")}</td>
                  <td>{item.observation_price?.toFixed(2) ?? "—"}</td>
                  <td>
                    {percent(
                      item.return_after_3_bars == null
                        ? null
                        : item.return_after_3_bars * 100,
                    )}
                  </td>
                  <td>
                    {percent(
                      item.return_after_5_bars == null
                        ? null
                        : item.return_after_5_bars * 100,
                    )}
                  </td>
                  <td>
                    {percent(
                      item.return_after_10_bars == null
                        ? null
                        : item.return_after_10_bars * 100,
                    )}
                  </td>
                  <td>
                    {percent(
                      item.maximum_favorable_excursion == null
                        ? null
                        : item.maximum_favorable_excursion * 100,
                    )}
                  </td>
                  <td>
                    {percent(
                      item.maximum_adverse_excursion == null
                        ? null
                        : item.maximum_adverse_excursion * 100,
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
