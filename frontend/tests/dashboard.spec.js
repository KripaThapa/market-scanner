import { test, expect } from "@playwright/test";

const stamp = "2026-09-13T18:00:00Z";
const row = (symbol, context) => ({
  symbol,
  context_10m: context,
  context_3m: "MIXED",
  setup_state: "NONE",
  sector: "Technology",
  candle_state: "COMPLETED",
  latest_price: 125.5,
  scanned_at: stamp,
});
function fixture() {
  return {
    state: { status: "idle", last_updated: stamp, scan_interval_seconds: 300 },
    counts: {
      total: 2,
      bullish: 1,
      bearish: 1,
      mixed: 0,
      no_data: 0,
      developing: 0,
      forming_long: 0,
      forming_short: 0,
      sectors_represented: 1,
    },
    watchlist: [row("NVDA", "BULLISH"), row("AMD", "BEARISH")],
    universe: [row("NVDA", "BULLISH"), row("AMD", "BEARISH")],
    setups: [],
    alerts: [],
    latest_upload: null,
    sectors: [
      {
        sector: "Technology",
        symbols: ["NVDA", "AMD"],
        bullish_count: 1,
        bearish_count: 1,
        mixed_count: 0,
        forming_long_count: 0,
        forming_short_count: 0,
        average_volatility: null,
        relative_strength: null,
      },
    ],
  };
}

async function mockAPI(page, body = fixture()) {
  await page.route("**/api/dashboard", (route) =>
    route.fulfill({ json: body }),
  );
  return body;
}

test("Discovery shows a source-agnostic universe with sector filtering and symbol navigation", async ({
  page,
}) => {
  const body = fixture();
  body.universe.push({
    ...row("MSFT", "BULLISH"),
    sector: "Software",
    setup_state: "FORMING_LONG",
  });
  await mockAPI(page, body);
  await page.route("**/api/symbols/MSFT", (route) =>
    route.fulfill({
      json: {
        symbol: "MSFT",
        context_10m: "BULLISH",
        context_3m: "MIXED",
        setup_state: "FORMING_LONG",
        candle_state: "PARTIAL",
        candles_3m: [],
        candles_10m: [],
      },
    }),
  );
  await page.goto("/");
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "Discovery" })
    .click();
  await expect(page.getByRole("link", { name: "MSFT →" })).toBeVisible();
  await expect(page.getByText("UPLOADED_WATCHLIST")).toHaveCount(0);
  await page.getByLabel("Sector").selectOption("Software");
  await expect(page.getByRole("link", { name: "NVDA →" })).toHaveCount(0);
  await page.getByRole("link", { name: "MSFT →" }).click();
  await expect(page).toHaveURL(/\/symbols\/MSFT$/);
  await expect(page.getByText("PARTIAL", { exact: true })).toBeVisible();
});

test("forming symbol opens scanner-backed detail charts and supports direct route", async ({
  page,
}) => {
  const body = fixture();
  body.setups = [
    {
      id: 1,
      symbol: "MSFT",
      direction: "LONG",
      context_10m: "BULLISH",
      setup_state: "FORMING_LONG",
      first_detected_at: stamp,
      last_seen_at: stamp,
    },
  ];
  const candle = (timestamp, close) => ({
    timestamp,
    open: close - 0.2,
    high: close + 0.4,
    low: close - 0.5,
    close,
    volume: 1200,
  });
  const candles = [
    candle("2026-09-13T09:30:00-04:00", 125),
    candle("2026-09-13T09:33:00-04:00", 124.8),
  ];
  await mockAPI(page, body);
  await page.route("**/api/symbols/MSFT", (route) =>
    route.fulfill({
      json: {
        symbol: "MSFT",
        setup_state: "FORMING_LONG",
        context_10m: "BULLISH",
        context_3m: "MIXED",
        candle_state: "COMPLETED",
        first_detected_at: stamp,
        last_seen_at: stamp,
        candles_10m: candles,
        candles_3m: candles,
      },
    }),
  );
  await page.goto("/");
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "Forming Setups" })
    .click();
  await page.getByRole("link", { name: "MSFT →" }).click();
  await expect(page).toHaveURL(/\/symbols\/MSFT$/);
  await expect(page.getByRole("heading", { name: "MSFT" })).toBeVisible();
  await expect(page.getByText("COMPLETED", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("img", { name: "10-minute context candlestick chart" }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", {
      name: "3-minute price candlestick chart",
    }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("img", {
      name: "3-minute price candlestick chart",
    }),
  ).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "MSFT" })).toBeVisible();
  await page.getByRole("button", { name: "← Forming Setups" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("link", { name: "MSFT →" })).toBeVisible();
});

test("navigation, sorting, filtering, sector drilldown and honest TBD states", async ({
  page,
}, testInfo) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await mockAPI(page);
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Dashboard", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "NVDA", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("dashboard.png"),
    fullPage: true,
  });
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "Discovery" })
    .click();
  await expect(page.getByRole("link", { name: "NVDA →" })).toBeVisible();
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "Sectors", exact: true })
    .click();
  await page.getByRole("button", { name: "Technology ↗" }).click();
  await expect(
    page.getByRole("heading", { name: "Technology", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "NVDA", exact: true }),
  ).toBeVisible();
  for (const [tab, text] of [
    ["Forming Setups", "No forming states reported"],
    ["Alerts", "Your alert history is empty"],
    ["Settings", "Scanner interval"],
  ]) {
    await page
      .getByRole("navigation")
      .getByRole("button", { name: tab, exact: true })
      .click();
    await expect(page.getByRole("heading", { name: text })).toBeVisible();
  }
  expect(errors).toEqual([]);
});

test("public scanner has no upload, rules, or research controls", async ({
  page,
}) => {
  await mockAPI(page);
  await page.goto("/");
  for (const name of ["Watchlist", "Rules", "Research"]) {
    await expect(
      page.getByRole("navigation").getByRole("button", { name }),
    ).toHaveCount(0);
  }
  await expect(page.getByLabel("Choose watchlist screenshot")).toHaveCount(0);
});

test("API failure is visible and retry recovers", async ({ page }) => {
  await page.route("**/api/dashboard", (route) =>
    route.fulfill({ status: 503, json: { detail: "Unavailable" } }),
  );
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText(
    "Cannot refresh scanner data",
  );
  await mockAPI(page);
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(
    page.getByRole("cell", { name: "NVDA", exact: true }),
  ).toBeVisible();
});

test("mobile navigation and tables remain usable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockAPI(page);
  await page.goto("/");
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "Discovery" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Discovery", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("periodic refresh retains stale data on errors and later recovers", async ({
  page,
}) => {
  await page.clock.install();
  await mockAPI(page);
  await page.goto("/");
  await expect(
    page.getByRole("cell", { name: "NVDA", exact: true }),
  ).toBeVisible();
  await page.route("**/api/dashboard", (route) =>
    route.fulfill({ status: 503, json: { detail: "Offline" } }),
  );
  await page.clock.fastForward(15000);
  await expect(page.getByRole("alert")).toContainText(
    "Cannot refresh scanner data",
  );
  await expect(
    page.getByRole("cell", { name: "NVDA", exact: true }),
  ).toBeVisible();
  await mockAPI(page, {
    ...fixture(),
    watchlist: [row("TSLA", "BULLISH")],
    universe: [row("TSLA", "BULLISH")],
  });
  await page.clock.fastForward(15000);
  await expect(
    page.getByRole("cell", { name: "TSLA", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("dashboard names scanner results and does not count Unknown as a known sector", async ({
  page,
}) => {
  const body = fixture();
  body.counts.sectors_represented = 0;
  body.counts.missing_sector_data = 2;
  body.universe.forEach((item) => {
    item.sector = "UNKNOWN";
  });
  body.sectors = [{ sector: "UNKNOWN", symbols: ["NVDA", "AMD"] }];
  await mockAPI(page, body);
  await page.goto("/");
  await expect(page.getByText("Stocks scanned", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Scanner results" }),
  ).toBeVisible();
  await expect(page.getByText("Active universe", { exact: true })).toHaveCount(
    0,
  );
  await expect(
    page.getByText("Universe overview", { exact: true }),
  ).toHaveCount(0);
  const metric = page.locator(".metric").filter({ hasText: "Known sectors" });
  await expect(metric.locator("strong")).toHaveText("0");
  await expect(metric).toContainText("2 stocks missing sector data");
});

test("recent alerts refresh, open stock detail, and render persisted FORMING markers", async ({
  page,
}, testInfo) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript(() => {
    window.renderedFormingLabels = [];
    const original = CanvasRenderingContext2D.prototype.fillText;
    CanvasRenderingContext2D.prototype.fillText = function (text, ...args) {
      if (text === "FORMING LONG" || text === "FORMING SHORT")
        window.renderedFormingLabels.push(text);
      return original.call(this, text, ...args);
    };
  });
  await page.clock.install();
  const body = fixture();
  const alert = (id, alert_type, decision_candle_at) => ({
    id,
    symbol: "NVDA",
    alert_type,
    decision_candle_at,
    timestamp: "2026-09-18T13:48:00Z",
    price: 125.5,
    context_10m: "BULLISH",
    reason: "Experimental forming state detected.",
  });
  body.alerts = [alert(1, "FORMING_LONG", "2026-09-18T13:42:00Z")];
  await mockAPI(page, body);
  await page.route("**/api/symbols/NVDA", (route) =>
    route.fulfill({
      json: {
        symbol: "NVDA",
        setup_state: "NONE",
        context_10m: "MIXED",
        context_3m: "MIXED",
        candles_10m: [],
        candles_3m: [
          "2026-09-18T09:42:00-04:00",
          "2026-09-18T09:45:00-04:00",
        ].map((timestamp) => ({
          timestamp,
          open: 125,
          close: 125.5,
          high: 126,
          low: 124,
          volume: 1000,
        })),
        alerts: body.alerts,
      },
    }),
  );
  await page.goto("/");
  const recent = page
    .locator("section")
    .filter({ has: page.getByRole("heading", { name: "Recent Alerts" }) });
  await expect(
    recent.getByRole("cell", { name: "FORMING LONG", exact: true }),
  ).toBeVisible();
  await expect(
    recent.getByRole("cell", { name: "125.50", exact: true }),
  ).toBeVisible();
  body.alerts.unshift(alert(2, "FORMING_SHORT", "2026-09-18T13:45:00Z"));
  await page.clock.fastForward(15000);
  await expect(
    recent.getByRole("cell", { name: "FORMING SHORT", exact: true }),
  ).toBeVisible();
  await recent.getByRole("link", { name: "NVDA →" }).first().click();
  await expect(page).toHaveURL(/\/symbols\/NVDA$/);
  await page.clock.resume();
  await expect
    .poll(() =>
      page.evaluate(() => [...new Set(window.renderedFormingLabels)].sort()),
    )
    .toEqual(["FORMING LONG", "FORMING SHORT"]);
  await page
    .locator("section")
    .filter({
      has: page.getByRole("heading", { name: "3-minute price", exact: true }),
    })
    .screenshot({ path: testInfo.outputPath("forming-markers.png") });
  expect(errors).toEqual([]);
});
