import React, { useMemo, useState } from "react";
import { Badge, Panel, Table, time } from "./components";

export default function Discovery({ rows, openSymbol }) {
  const [sector, setSector] = useState("");
  const sectors = useMemo(
    () => [...new Set(rows.map((row) => row.sector))].sort(),
    [rows],
  );
  const visible = sector ? rows.filter((row) => row.sector === sector) : rows;
  return (
    <>
      <div className="notice">
        The active universe combines current candidates. Context and setup
        states are scanner observations, not trade signals.
      </div>
      <Panel title="Active universe" subtitle="One scan per symbol">
        <label className="discovery-filter">
          Sector
          <select
            value={sector}
            onChange={(event) => setSector(event.target.value)}
          >
            <option value="">All sectors</option>
            {sectors.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        </label>
        <Table
          label="active universe"
          rows={visible}
          emptyTitle="No active symbols"
          emptyText="Candidates appear when a watchlist is uploaded or morning discovery returns symbols."
          columns={[
            {
              key: "symbol",
              label: "Symbol",
              render: (value) => (
                <a
                  href={`/symbols/${encodeURIComponent(value)}`}
                  className="symbol-link"
                  onClick={(event) => {
                    event.preventDefault();
                    openSymbol(value);
                  }}
                >
                  {value} →
                </a>
              ),
            },
            { key: "sector", label: "Sector" },
            { key: "latest_price", label: "Price" },
            {
              key: "percent_change",
              label: "% change",
              render: (value) =>
                value == null ? "—" : `${Number(value).toFixed(2)}%`,
            },
            {
              key: "context_10m",
              label: "10m",
              render: (value) => <Badge value={value} />,
            },
            {
              key: "context_3m",
              label: "3m",
              render: (value) => <Badge value={value} />,
            },
            { key: "setup_state", label: "Setup" },
            { key: "candle_state", label: "3m candle" },
            { key: "scanned_at", label: "Updated", render: time },
          ]}
        />
      </Panel>
    </>
  );
}
