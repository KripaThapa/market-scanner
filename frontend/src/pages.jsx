import React, { useState } from "react";
import { Panel, Table, Empty, time, alertColumns } from "./components";

export function Dashboard({ data, navigate, openSymbol }) {
  const counts = data?.counts || {},
    rows = data?.universe || [],
    sectors = data?.sectors || [];
  const metrics = [
    ["Stocks scanned", counts.total, "Unique symbols scanned", ""],
    ["Bullish context", counts.bullish, "10-minute trend", "green"],
    ["Bearish context", counts.bearish, "10-minute trend", "red"],
    ["Mixed context", counts.mixed, "10-minute trend", "yellow"],
    ["Forming long", counts.forming_long, "Current scanner states", ""],
    ["Forming short", counts.forming_short, "Current scanner states", ""],
    [
      "Known sectors",
      counts.sectors_represented,
      `${counts.missing_sector_data ?? 0} stocks missing sector data`,
      "",
    ],
    ["No market data", counts.no_data, "Excluded from context counts", ""],
  ];
  return (
    <>
      <div className="metrics">
        {metrics.map(([label, value, sub, tone]) => (
          <div className={`metric ${tone}`} key={label}>
            <span>{label}</span>
            <strong>{value ?? "—"}</strong>
            <small>{sub}</small>
          </div>
        ))}
      </div>
      <div className="dashboard-grid">
        <Panel
          title="Market context"
          subtitle="10-minute context across stocks scanned"
          action={<span className="small-label">CONTEXT ONLY</span>}
        >
          <div className="breadth">
            <div className="breadth-bar">
              {[
                ["bullish", "green"],
                ["bearish", "red"],
                ["mixed", "yellow"],
                ["no_data", "neutral"],
              ].map(([key, tone]) => (
                <span
                  key={key}
                  className={tone}
                  style={{ flex: counts[key] || 0 }}
                />
              ))}
            </div>
            <div className="legend">
              {[
                ["bullish", "green"],
                ["bearish", "red"],
                ["mixed", "yellow"],
              ].map(([key, tone]) => (
                <span key={key}>
                  <i className={tone} />
                  {key}
                  <strong>{counts[key] ?? "—"}</strong>
                </span>
              ))}
            </div>
            <p className="muted">
              Context is observational. No entry signal is produced.
            </p>
          </div>
        </Panel>
        <Panel title="Scanner status" subtitle="Last persisted run">
          <div className="status-list">
            <div>
              <span>State</span>
              <strong>{data?.state.status || "Waiting for API"}</strong>
            </div>
            <div>
              <span>Latest successful scan</span>
              <strong>{time(data?.state.last_updated)}</strong>
            </div>
          </div>
        </Panel>
      </div>
      <Panel
        title="Scanner results"
        subtitle="Current context, not entry signals"
        action={
          <button className="text-button" onClick={() => navigate("Discovery")}>
            View stocks →
          </button>
        }
      >
        <Table
          rows={rows}
          columns={[
            { key: "symbol", label: "Symbol" },
            { key: "sector", label: "Sector" },
            { key: "context_10m", label: "10m context" },
            { key: "setup_state", label: "Setup" },
          ]}
          contextFilter
          label="overview"
        />
      </Panel>
      <div className="dashboard-grid">
        <Panel
          title="Recent Alerts"
          subtitle="Completed-candle FORMING transitions"
          action={
            <button className="text-button" onClick={() => navigate("Alerts")}>
              View all →
            </button>
          }
        >
          <Table
            label="recent alerts"
            rows={(data?.alerts || []).slice(0, 5)}
            columns={alertColumns(openSymbol)}
            emptyTitle="No FORMING alerts yet"
            emptyText="Experimental FORMING transitions will appear here. FORMING is not a trade entry."
          />
        </Panel>
        <Panel
          title="Sector coverage"
          subtitle="Current universe counts"
          action={
            <button className="text-button" onClick={() => navigate("Sectors")}>
              Explore →
            </button>
          }
        >
          {sectors.length ? (
            <div className="sector-list">
              {sectors.slice(0, 5).map((sector) => (
                <div key={sector.sector}>
                  <div>
                    <strong>{sector.sector}</strong>
                    <span>{sector.symbols.length} symbols</span>
                  </div>
                  <div className="coverage-track">
                    <span
                      style={{
                        width: `${(100 * sector.symbols.length) / (counts.total || 1)}%`,
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <Empty title="No sector activity" index={4}>
              Coverage will appear after a successful scan.
            </Empty>
          )}
        </Panel>
      </div>
    </>
  );
}

export function Sectors({ sectors, rows }) {
  const [selected, setSelected] = useState(null);
  const current = sectors.find((sector) => sector.sector === selected);
  return (
    <>
      <div className="notice">
        Sector data shows objective counts. Symbols without configured sector
        metadata appear as UNKNOWN.
      </div>
      <Panel
        title="Sector activity"
        subtitle="Select a sector to inspect its symbols"
      >
        <Table
          label="sectors"
          rows={sectors.map((s) => ({ ...s, symbol_count: s.symbols.length }))}
          emptyTitle="No sector data yet"
          columns={[
            {
              key: "sector",
              label: "Sector",
              render: (v) => (
                <button className="text-button" onClick={() => setSelected(v)}>
                  {v} ↗
                </button>
              ),
            },
            { key: "symbol_count", label: "Symbols" },
            { key: "bullish_count", label: "Bullish" },
            { key: "bearish_count", label: "Bearish" },
            { key: "mixed_count", label: "Mixed" },
            { key: "forming_long_count", label: "Forming long" },
            { key: "forming_short_count", label: "Forming short" },
          ]}
        />
      </Panel>
      {current && (
        <Panel
          title={current.sector}
          subtitle={`${current.symbols.length} symbols in this sector`}
          action={
            <button className="text-button" onClick={() => setSelected(null)}>
              Close ×
            </button>
          }
        >
          <Table
            label="sector symbols"
            columns={[
              { key: "symbol", label: "Symbol" },
              { key: "context_10m", label: "10m" },
              { key: "setup_state", label: "Setup" },
              { key: "candle_state", label: "3m candle" },
            ]}
            rows={rows.filter((row) => current.symbols.includes(row.symbol))}
            contextFilter
          />
        </Panel>
      )}
    </>
  );
}
