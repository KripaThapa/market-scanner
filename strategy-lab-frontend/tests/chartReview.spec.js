import { test, expect } from "@playwright/test";

const day = "2026-09-18";
const base = Date.parse(`${day}T13:30:00Z`);
const rows = (step, count) =>
  Array.from({ length: count }, (_, i) => {
    const close = 186.4 + Math.sin(i / 4) * 0.65 + i * 0.024;
    return {
      timestamp: new Date(base + i * step * 60000).toISOString(),
      open: close - 0.12,
      high: close + 0.2,
      low: close - 0.3,
      close,
      volume: 1300,
      ema_5: close - 0.1,
      ema_12: close - 0.23,
      ema_34: close - 0.4,
      ema_50: close - 0.51,
      vwap: 186.7,
    };
  });
const chart = () => ({
  date: day,
  symbol: "NVDA",
  timezone: "America/New_York",
  legacy_date: false,
  levels: [
    { direction: "LONG", price: 187.5 },
    { direction: "SHORT", price: 184.2 },
  ],
  candles_3m: rows(3, 90),
  candles_10m: rows(10, 27),
  event_basis: "Recorded scanner alerts",
  chart_note:
    "Retrospective stored candles; later revisions may differ from alert-time evidence.",
  events: [
    {
      id: "alert-1",
      type: "FORMING_LONG",
      timestamp: new Date(base + 33 * 60000).toISOString(),
      chart_time: new Date(base + 30 * 60000).toISOString(),
      price: 186.84,
      context_10m: "BULLISH",
      vwap_position: "ABOVE",
      origin: "Recorded scanner alert",
      outcome: {
        returns: { 9: 0.007, 15: 0.011, 30: null },
        best_move: 0.018,
        adverse_move: -0.002,
        window: {
          start: new Date(base + 33 * 60000).toISOString(),
          end: new Date(base + 63 * 60000).toISOString(),
          label: "Next 10 recorded 3-minute bars · relative to alert direction",
        },
      },
    },
    {
      id: "level-2",
      type: "WATCHLIST_LEVEL_LONG",
      timestamp: new Date(base + 45 * 60000).toISOString(),
      chart_time: new Date(base + 45 * 60000).toISOString(),
      price: 187.52,
      trigger_level: 187.5,
      origin: "Recorded level crossing",
      outcome: {
        returns: { 9: null, 15: null, 30: null },
        best_move: null,
        adverse_move: null,
      },
    },
  ],
});
async function mock(page, data = chart()) {
  await page.route(
    "**/api/internal/strategy-lab/review/watchlist?**",
    (route) => route.fulfill({ json: { date: day, symbols: ["NVDA", "AMD"] } }),
  );
  await page.route("**/api/internal/strategy-lab/review/chart?**", (route) =>
    route.fulfill({
      json: {
        ...data,
        symbol: new URL(route.request().url()).searchParams.get("symbol"),
      },
    }),
  );
}
test("chart-first watchlist review shows two real charts, levels and compact event outcomes", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await mock(page);
  await page.goto("/");
  await page.getByLabel("Watchlist date").fill(day);
  await expect(page.getByLabel("Watchlist stock")).toHaveValue("NVDA");
  await expect(
    page.getByRole("heading", { name: "10 MIN — MARKET STRUCTURE" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "3 MIN — SETUP" }),
  ).toBeVisible();
  await expect(page.locator(".review-charts canvas").first()).toBeVisible();
  await expect(
    page.getByText("Supplied levels: LONG $187.50 · SHORT $184.20"),
  ).toBeVisible();
  await page.getByRole("button", { name: /FORMING LONG/ }).click();
  const outcome = page.locator(".review-outcome");
  await expect(outcome).toContainText("+0.7%");
  await expect(outcome).toContainText("−0.2%".replace("−", "-"));
  await expect(outcome).toContainText("30 min laterUnavailable");
  await expect(page.locator(".event-detail")).toContainText("bullish");
  await page.getByRole("button", { name: /LEVEL LONG/ }).click();
  await expect(page.locator(".event-detail")).toContainText("$187.52");
  await expect(page.locator(".event-detail")).toContainText("$187.50");
  await expect(outcome).toContainText("Unavailable");
  await page.getByLabel("Watchlist stock").selectOption("AMD");
  await expect(page.locator(".review-heading h2")).toHaveText("AMD");
  await expect(page.locator(".event-detail")).toHaveCount(0);
  expect(errors).toEqual([]);
});
test("missing history and outcomes are honest, no invented level or marker", async ({
  page,
}) => {
  await mock(page, {
    ...chart(),
    levels: [],
    events: [],
    candles_3m: [],
    candles_10m: [],
  });
  await page.goto("/");
  await expect(
    page.getByText("No stored candles available for this timeframe."),
  ).toHaveCount(2);
  await expect(
    page.getByText("No persisted events for this symbol and date."),
  ).toBeVisible();
  await expect(page.locator(".review-levels")).toHaveCount(0);
});
test("clicking an event candle opens its persisted details", async ({
  page,
}) => {
  await mock(page);
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto("/");
  const node = page.getByLabel("3 MIN — SETUP candlestick chart");
  await expect(node.locator("canvas").first()).toBeVisible();
  await node.scrollIntoViewIfNeeded();
  const box = await node.boundingBox();
  // Walk the first event's candle area; canvas has no DOM hit target.
  for (let x = 40; x < box.width * 0.25; x += 4) {
    await page.mouse.click(box.x + x, box.y + 160);
    if (await page.locator(".event-detail").count()) break;
  }
  await expect(page.locator(".event-detail")).toContainText("FORMING LONG");
  await expect(page.locator(".event-detail")).toContainText("$186.84");
});
test("no uploaded watchlist never offers discovery/manual symbols", async ({
  page,
}) => {
  await page.route(
    "**/api/internal/strategy-lab/review/watchlist?**",
    (route) => route.fulfill({ json: { symbols: [] } }),
  );
  await page.goto("/");
  await expect(
    page.getByText("No uploaded watchlist stored for this date."),
  ).toBeVisible();
  await expect(page.getByLabel("Watchlist stock")).toBeDisabled();
  await expect(page.getByText("All scanned", { exact: true })).toHaveCount(0);
});
test("responsive charts and tooltip retain readable ET axes", async ({
  page,
}, info) => {
  await mock(page);
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto("/");
  await page.getByLabel("Watchlist date").fill("2026-09-18");
  await page.getByRole("button", { name: /FORMING LONG/ }).click();
  await expect(page.locator(".review-charts canvas").first()).toBeVisible();
  const chartNode = page.getByLabel("3 MIN — SETUP candlestick chart");
  await chartNode.scrollIntoViewIfNeeded();
  const box = await chartNode.boundingBox();
  await page.mouse.move(box.x + box.width * 0.6, box.y + 150);
  await expect(page.locator(".chart-tooltip:visible")).toContainText("ET");
  await page.screenshot({
    path: info.outputPath("lab-review-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("heading", { name: "3 MIN — SETUP" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
});
