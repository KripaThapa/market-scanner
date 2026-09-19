import React, { useState } from "react";

const paths = [
  "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  "M4 5h16 M4 12h16 M4 19h16",
  "M3 17l5-6 5 3 8-10 M16 4h5v5",
  "M4 19V5h16 M7 15l4-4 3 2 4-5",
  "M4 6h16 M4 12h16 M4 18h12",
  "M5 17h14l-2-4V8a5 5 0 0 0-10 0v5z M10 21h4",
  "M4 20V10h4v10 M10 20V4h4v16 M16 20v-7h4v7",
  "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M12 2v3 M12 19v3 M2 12h3 M19 12h3 M5 5l2 2 M17 17l2 2 M5 19l2-2 M17 7l2-2",
];
export function Icon({ index = 0 }) {
  return (
    <svg
      width="19"
      height="19"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[index]} />
    </svg>
  );
}
export const time = (value) =>
  value ? new Date(value).toLocaleString() : "Not yet scanned";
const price = (value) =>
  value == null
    ? "—"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
      }).format(value);
export function Badge({ value }) {
  const tone =
    {
      BULLISH: "green",
      ABOVE: "green",
      BEARISH: "red",
      BELOW: "red",
      MIXED: "yellow",
    }[value] || "neutral";
  return (
    <span className={`badge ${tone}`}>
      <i />
      {value || "UNAVAILABLE"}
    </span>
  );
}
export function Empty({ title, children, index = 2 }) {
  return (
    <div className="empty">
      <div className="empty-icon">
        <Icon index={index} />
      </div>
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
export function Panel({ title, subtitle, action, children }) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <h2>{title}</h2>
          {subtitle && <p>{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export function Table({
  columns,
  rows,
  emptyTitle = "No results yet",
  emptyText = "Results will appear after the next successful scan.",
  contextFilter = false,
  label = "table",
}) {
  const [search, setSearch] = useState(""),
    [context, setContext] = useState("ALL"),
    [sort, setSort] = useState({ key: null, direction: 1 });
  const filtered = rows.filter(
    (row) =>
      columns.some((col) =>
        String(row[col.key] ?? "")
          .toLowerCase()
          .includes(search.toLowerCase()),
      ) &&
      (context === "ALL" || row.context_10m === context),
  );
  const sorted = [...filtered].sort((a, b) => {
    if (!sort.key) return 0;
    const x = a[sort.key],
      y = b[sort.key];
    if (x == null) return y == null ? 0 : 1;
    if (y == null) return -1;
    return (
      (typeof x === "number" && typeof y === "number"
        ? x - y
        : String(x).localeCompare(String(y))) * sort.direction
    );
  });
  return (
    <>
      <div className="table-tools">
        <label className="search">
          <span aria-hidden="true">⌕</span>
          <input
            aria-label={`Search ${label}`}
            placeholder="Search symbols or values…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        {contextFilter && (
          <select
            aria-label={`Filter ${label} by context`}
            value={context}
            onChange={(e) => setContext(e.target.value)}
          >
            <option value="ALL">All contexts</option>
            {["BULLISH", "BEARISH", "MIXED", "NO DATA", "PENDING"].map((v) => (
              <option key={v}>{v}</option>
            ))}
          </select>
        )}
        <span className="row-count">
          {filtered.length} {filtered.length === 1 ? "result" : "results"}
        </span>
      </div>
      {!sorted.length ? (
        <Empty title={rows.length ? "No matching results" : emptyTitle}>
          {rows.length ? "Try another search or context filter." : emptyText}
        </Empty>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                {columns.map((col) => (
                  <th
                    key={col.key}
                    aria-sort={
                      sort.key === col.key
                        ? sort.direction === 1
                          ? "ascending"
                          : "descending"
                        : "none"
                    }
                  >
                    <button
                      onClick={() =>
                        setSort({
                          key: col.key,
                          direction: sort.key === col.key ? -sort.direction : 1,
                        })
                      }
                    >
                      {col.label}
                      <span>
                        {sort.key === col.key
                          ? sort.direction === 1
                            ? " ↑"
                            : " ↓"
                          : " ↕"}
                      </span>
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((row, index) => (
                <tr key={row.id ?? row.symbol ?? row.sector ?? index}>
                  {columns.map((col) => (
                    <td key={col.key}>
                      {col.render
                        ? col.render(row[col.key], row)
                        : (row[col.key] ?? "—")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
export const alertColumns = [
  { key: "timestamp", label: "Timestamp", render: time },
  { key: "symbol", label: "Symbol" },
  { key: "alert_type", label: "Type" },
];
