import React, { useEffect, useState } from "react";
import { Icon, Panel, Table, Badge, time, alertColumns } from "./components";
import { useDashboard } from "./api";
import { Dashboard, Sectors } from "./pages";
import SymbolDetail from "./SymbolDetail";
import Discovery from "./Discovery";

const pages = [
  "Dashboard",
  "Discovery",
  "Forming Setups",
  "Alerts",
  "Sectors",
  "Settings",
];
const descriptions = {
  Dashboard: "A clear view of the active universe and market context.",
  Discovery: "The current scanning universe and market context.",
  "Forming Setups": "Developing states reported by the scanner.",
  Alerts: "A record of scanner events and delivery status.",
  Sectors: "Objective counts across the active universe.",
  Settings: "A preview of future scanner configuration.",
};
export default function App() {
  const [page, setPage] = useState("Dashboard");
  const [path, setPath] = useState(window.location.pathname);
  useEffect(() => {
    const update = () => setPath(window.location.pathname);
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);
  const symbol = /^\/symbols\/([A-Z0-9.-]+)$/i.exec(path)?.[1]?.toUpperCase();
  const navigate = (name) => {
    setPage(name);
    if (window.location.pathname !== "/") window.history.pushState({}, "", "/");
    setPath("/");
  };
  const openSymbol = (ticker) => {
    const next = `/symbols/${encodeURIComponent(ticker)}`;
    window.history.pushState({}, "", next);
    setPath(next);
  };
  const { data, error, loading, refresh } = useDashboard();
  const busy = ["importing", "scanning"].includes(data?.state.status);
  return (
    <div className="app">
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            navigate("Dashboard");
          }}
        >
          <span className="brand-mark">
            M<span>↗</span>
          </span>
          <span>
            MARKET<small>SCANNER</small>
          </span>
        </a>
        <div className="nav-label">WORKSPACE</div>
        <nav aria-label="Main navigation">
          {pages.map((name, i) => (
            <button
              key={name}
              className={!symbol && page === name ? "active" : ""}
              aria-current={!symbol && page === name ? "page" : undefined}
              onClick={() => navigate(name)}
            >
              <Icon index={i} />
              <span>{name}</span>
              {name === "Alerts" && data?.alerts.length > 0 && (
                <small>{data.alerts.length}</small>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <span className="read-only-dot" /> Scanner
          <p>Market context. No trade execution.</p>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <span>
            WORKSPACE <span className="slash">/</span>{" "}
            <strong>{symbol ? symbol : page}</strong>
          </span>
          <span className="mode">READ-ONLY SCANNER</span>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">MARKET SCANNER</div>
              <h1>{symbol || page}</h1>
              <p>
                {symbol
                  ? "Scanner-persisted price structure and experimental setup context."
                  : descriptions[page]}
              </p>
            </div>
            <div className="refresh-meta">
              <span className={`connection ${error ? "offline" : ""}`}>
                <i />
                {error
                  ? "API unavailable"
                  : loading
                    ? "Connecting"
                    : busy
                      ? "Scanner processing"
                      : "Auto-refresh · 15s"}
              </span>
              <small>Last updated: {time(data?.state.last_updated)}</small>
            </div>
          </div>
          {error && (
            <div className="error" role="alert">
              {error}{" "}
              <button className="text-button" onClick={refresh}>
                Retry
              </button>
            </div>
          )}
          {data?.counts.pending > 0 && (
            <div className="notice">
              {data.counts.pending} symbols are waiting for the scanner. Results
              refresh automatically.
            </div>
          )}
          {loading && (
            <div className="notice" role="status">
              Loading scanner state…
            </div>
          )}
          {symbol && (
            <SymbolDetail
              symbol={symbol}
              onBack={() => navigate("Forming Setups")}
              scanUpdated={data?.state.last_updated}
            />
          )}
          {!symbol && page === "Dashboard" && (
            <Dashboard data={data} navigate={navigate} />
          )}
          {!symbol && page === "Discovery" && (
            <Discovery rows={data?.universe || []} openSymbol={openSymbol} />
          )}
          {!symbol && page === "Forming Setups" && (
            <>
              <div className="notice">
                Forming states are scanner observations, not entry signals.
              </div>
              <Panel
                title="Forming setups"
                subtitle="Active backend-detected pullbacks"
              >
                <Table
                  label="setups"
                  rows={data?.setups || []}
                  emptyTitle="No forming states reported"
                  emptyText="No symbols currently meet the experimental forming conditions."
                  columns={[
                    {
                      key: "symbol",
                      label: "Symbol",
                      render: (v) => (
                        <a
                          className="symbol-link"
                          href={`/symbols/${encodeURIComponent(v)}`}
                          onClick={(event) => {
                            event.preventDefault();
                            openSymbol(v);
                          }}
                        >
                          {v} →
                        </a>
                      ),
                    },
                    { key: "direction", label: "Direction" },
                    {
                      key: "context_10m",
                      label: "10m context",
                      render: (v) => <Badge value={v} />,
                    },
                    { key: "setup_state", label: "Status" },
                    { key: "price", label: "3m price" },
                    {
                      key: "first_detected_at",
                      label: "First detected",
                      render: time,
                    },
                    {
                      key: "last_seen_at",
                      label: "Last updated",
                      render: time,
                    },
                  ]}
                />
              </Panel>
            </>
          )}
          {!symbol && page === "Alerts" && (
            <Panel
              title="Alert history"
              subtitle="Latest 200 stored events · generation and delivery TBD"
            >
              <Table
                label="alerts"
                rows={data?.alerts || []}
                columns={alertColumns}
                emptyTitle="Your alert history is empty"
                emptyText="No alert rules or delivery integrations have been implemented."
              />
            </Panel>
          )}
          {!symbol && page === "Sectors" && (
            <Sectors
              sectors={data?.sectors || []}
              rows={data?.universe || []}
            />
          )}{" "}
          {!symbol && page === "Settings" && (
            <>
              <div className="notice">
                Configuration controls are placeholders. Settings cannot be
                changed from this dashboard.
              </div>
              <div className="settings-grid">
                {[
                  [
                    "Alert configuration",
                    "Alert rules and destinations remain undefined.",
                    5,
                  ],
                  [
                    "Scanner interval",
                    `Backend interval: ${data?.state.scan_interval_seconds ?? "—"} seconds. UI configuration is planned.`,
                    6,
                  ],
                  [
                    "Telegram settings",
                    "Telegram delivery is not connected. No credentials are shown or collected.",
                    7,
                  ],
                ].map(([title, text, index]) => (
                  <section className="panel setting" key={title}>
                    <Icon index={index} />
                    <span className="small-label">FUTURE / TBD</span>
                    <h2>{title}</h2>
                    <p>{text}</p>
                    <button disabled>Not available yet</button>
                  </section>
                ))}
              </div>
            </>
          )}
          <footer>
            10m context · 3m setup state{" "}
            <span>Observation only. No order entry or execution.</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
