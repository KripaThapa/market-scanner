import React, { useEffect, useMemo, useState } from "react";

export default function StockSelector({ universe, value, onChange }) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [manual, setManual] = useState(false);
  useEffect(() => setQuery(value || ""), [value]);
  const groups = useMemo(
    () =>
      (universe?.groups || [])
        .map((group) => ({
          ...group,
          symbols: group.symbols.filter((symbol) =>
            symbol.includes(query.trim().toUpperCase()),
          ),
        }))
        .filter((group) => group.symbols.length),
    [universe, query],
  );
  const options = groups.flatMap((group) => group.symbols);
  const choose = (symbol) => {
    onChange(symbol);
    setQuery(symbol);
    setOpen(false);
  };
  const keyDown = (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setActive((active + 1) % Math.max(options.length, 1));
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setOpen(true);
      setActive(
        (active - 1 + Math.max(options.length, 1)) %
          Math.max(options.length, 1),
      );
    }
    if (event.key === "Enter" && open && options[active]) {
      event.preventDefault();
      choose(options[active]);
    }
    if (event.key === "Escape") setOpen(false);
  };
  if (!universe) return <p>Loading historical scanner universe…</p>;
  if (!universe.recorded && !manual)
    return (
      <div className="empty-universe">
        <p>No scanner universe was recorded for this date.</p>
        <button type="button" onClick={() => setManual(true)}>
          Enter symbol manually
        </button>
      </div>
    );
  if (manual)
    return (
      <label>
        Stock symbol
        <input
          value={value}
          placeholder="Enter symbol"
          maxLength={20}
          onChange={(event) => onChange(event.target.value.toUpperCase())}
        />
      </label>
    );
  return (
    <div className="combobox-field">
      <label htmlFor="stock-search">Stock</label>
      <input
        id="stock-search"
        role="combobox"
        aria-expanded={open}
        aria-controls="stock-options"
        aria-autocomplete="list"
        placeholder="Search scanner universe…"
        value={query}
        onFocus={() => setOpen(true)}
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
          setActive(0);
        }}
        onKeyDown={keyDown}
      />
      {value && <small>Selected: {value}</small>}
      {open && (
        <div className="stock-options" id="stock-options" role="listbox">
          {groups.map((group) => (
            <div key={group.id} className="stock-group">
              <strong>{group.label}</strong>
              {group.symbols.map((symbol) => {
                const index = options.indexOf(symbol);
                return (
                  <button
                    type="button"
                    role="option"
                    aria-selected={value === symbol}
                    className={index === active ? "active" : ""}
                    key={symbol}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => choose(symbol)}
                  >
                    {symbol}
                  </button>
                );
              })}
            </div>
          ))}
          {!options.length && <p>No matching symbols.</p>}
        </div>
      )}
    </div>
  );
}
