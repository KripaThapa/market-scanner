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
  useEffect(() => {
    request("/api/internal/strategy-lab/baseline")
      .then((value) => {
        setReport(value);
        if (value.id)
          return request(
            `/api/internal/strategy-lab/baseline/episodes?run_id=${value.id}`,
          );
      })
      .then((value) => value && setEpisodes(value.items))
      .catch((failure) => setError(failure.message));
  }, []);
  if (error) return <section className="error">{error}</section>;
  if (!report) return <p>Loading historical baseline…</p>;
  if (report.status === "NOT_RUN")
    return (
      <section className="baseline-empty">
        <h2>Historical Strategy Baseline</h2>
        <p>No baseline backfill has been run yet.</p>
      </section>
    );
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
      <section className="baseline-summary">
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
          <span>Trading days</span>
          <strong>
            {report.coverage.trading_days_completed} /{" "}
            {report.coverage.trading_days}
          </strong>
        </div>
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
