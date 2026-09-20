import { test, expect } from "@playwright/test";

const stamp = (minute) => `2026-09-18T13:${minute}:00+00:00`;
const priorStamp = (minute) => `2026-09-17T13:${minute}:00+00:00`;
const candle = (minute) => ({
  timestamp: stamp(minute),
  open: 100,
  high: 101,
  low: 99,
  close: 100.5,
  volume: 1000,
  ema_5: 100,
  ema_12: 99.9,
  ema_34: 99.5,
  ema_50: 99,
  vwap: 100.1,
});
const priorCandle = (minute) => ({
  ...candle(minute),
  timestamp: priorStamp(minute),
});
const replay = (minute = "42", observations = []) => ({
  id: 1,
  instrument: "SPY",
  asset_type: "EQUITY",
  market_date: "2026-09-18",
  timezone: "America/Chicago",
  visible_start: stamp("30"),
  visible_end: "2026-09-18T15:00:00+00:00",
  current_replay_time: stamp(minute),
  status: "IN_PROGRESS",
  blind_mode: true,
  outcome_revealed: false,
  provider: "Fixture",
  feed: "TEST",
  context_10m: "BULLISH",
  state_3m: "NONE",
  detector_reason: null,
  candles_3m: [
    priorCandle("30"),
    candle("30"),
    candle("33"),
    candle("36"),
    candle("39"),
  ],
  candles_10m: [priorCandle("30"), candle("30")],
  forming_markers: [],
  observations,
});

const september = {
  market: "US_EQUITY",
  year: 2026,
  month: 9,
  default_date: "2026-09-18",
  days: Array.from({ length: 30 }, (_, index) => {
    const day = index + 1;
    const date = `2026-09-${String(day).padStart(2, "0")}`;
    if (day > 18) return { date, status: "UNAVAILABLE", reason: "FUTURE_DATE" };
    if ([5, 6, 12, 13].includes(day))
      return { date, status: "CLOSED", reason: "WEEKEND" };
    if (day === 7) return { date, status: "CLOSED", reason: "MARKET_HOLIDAY" };
    return { date, status: "OPEN", reason: null };
  }),
};
const universe = {
  trading_date: "2026-09-18",
  recorded: true,
  symbols: ["AMD", "MSFT", "NVDA", "SPY"],
  groups: [
    { id: "FORMING", label: "Forming that day", symbols: ["NVDA"] },
    { id: "DISCOVERY", label: "Discovery candidates", symbols: ["AMD", "SPY"] },
    { id: "ALL_SCANNED", label: "All scanned", symbols: ["MSFT"] },
  ],
};

async function mockCreationData(page, selectedUniverse = universe) {
  await page.route("**/api/internal/strategy-lab/calendar?**", (route) =>
    route.fulfill({ json: september }),
  );
  await page.route(
    "**/api/internal/strategy-lab/calendar/adjacent?**",
    (route) => {
      const direction = new URL(route.request().url()).searchParams.get(
        "direction",
      );
      return route.fulfill({
        json: { date: direction === "previous" ? "2026-09-17" : "2026-09-18" },
      });
    },
  );
  await page.route("**/api/internal/strategy-lab/universe?**", (route) =>
    route.fulfill({ json: selectedUniverse }),
  );
  await page.route("**/api/internal/strategy-lab/capabilities", (route) =>
    route.fulfill({
      json: {
        asset_types: {
          FUTURE: {
            supported: false,
            limitation:
              "MES futures replay requires a compatible historical-data provider.",
          },
        },
      },
    }),
  );
}

test("private replay advances visually, saves free text, and reveals only explicitly", async ({
  page,
}) => {
  let current = replay(),
    observations = [];
  await mockCreationData(page);
  await page.route("**/api/internal/replays", async (route) => {
    if (route.request().method() === "POST")
      return route.fulfill({ status: 201, json: current });
    return route.fulfill({ json: { items: [] } });
  });
  await page.route("**/api/internal/replays/1/next", (route) => {
    current = {
      ...replay("45", observations),
      candles_3m: [...replay("42").candles_3m, candle("42")],
    };
    return route.fulfill({ json: current });
  });
  await page.route("**/api/internal/replays/1/observations", async (route) => {
    observations = [
      {
        id: 7,
        replay_time: current.current_replay_time,
        decision: "WOULD_CONSIDER_ENTRY",
        free_text_reason: "Price held the area I was watching.",
      },
    ];
    return route.fulfill({ status: 201, json: observations[0] });
  });
  await page.route("**/api/internal/replays/1", (route) =>
    route.fulfill({ json: { ...current, observations } }),
  );
  await page.route("**/api/internal/replays/1/reveal", (route) =>
    route.fulfill({
      json: {
        replay_id: 1,
        label: "POST-OBSERVATION MARKET MOVEMENT",
        items: [],
      },
    }),
  );
  await page.goto("/");
  await page.getByRole("combobox", { name: "Stock" }).fill("SP");
  await page.getByRole("option", { name: "SPY" }).click();
  await page.getByRole("button", { name: "Start blind replay" }).click();
  await expect(page.getByText("08:42 CT", { exact: true })).toBeVisible();
  await expect(page.getByText("America/Chicago · CT")).toHaveCount(2);
  await expect(
    page.getByTestId("10-minute context-session-divider"),
  ).toBeVisible();
  await expect(
    page.getByTestId("3-minute setup research-session-divider"),
  ).toBeVisible();
  await expect(
    page.getByTestId("3-minute setup research-replay-edge"),
  ).toContainText("NOW · 08:42 CT");
  const chartBox = await page
    .getByLabel("3-minute setup research candlestick chart")
    .boundingBox();
  await page.mouse.move(
    chartBox.x + chartBox.width * 0.72,
    chartBox.y + chartBox.height * 0.5,
  );
  await expect(page.locator(".chart-tooltip").last()).toContainText("CT");
  await expect(page.locator(".chart-tooltip").last()).toContainText("Volume");
  await expect(page.locator(".chart-tooltip").last()).toContainText("EMA 5");
  const before = await page
    .getByLabel("3-minute setup research candlestick chart")
    .screenshot();
  await page.getByRole("button", { name: "Next candle" }).click();
  await expect(page.getByText("08:45 CT", { exact: true })).toBeVisible();
  await expect(
    page.getByTestId("3-minute setup research-replay-edge"),
  ).toContainText("NOW · 08:45 CT");
  const after = await page
    .getByLabel("3-minute setup research candlestick chart")
    .screenshot();
  expect(after.equals(before)).toBeFalsy();
  await page.screenshot({
    path: "../docs/images/strategy-lab-replay-chart.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "WOULD CONSIDER ENTRY" }).click();
  await page.getByLabel("Why?").fill("Price held the area I was watching.");
  await page.getByRole("button", { name: "Save observation" }).click();
  await expect(
    page.getByText("Price held the area I was watching."),
  ).toBeVisible();
  await expect(page.getByText("POST-OBSERVATION MARKET MOVEMENT")).toHaveCount(
    0,
  );
  await page.getByRole("button", { name: "Reveal outcome" }).click();
  await expect(
    page.getByRole("heading", { name: "POST-OBSERVATION MARKET MOVEMENT" }),
  ).toBeVisible();
});

test("calendar, historical groups, keyboard search, and session defaults", async ({
  page,
}) => {
  let payload;
  await mockCreationData(page);
  await page.route("**/api/internal/replays", async (route) => {
    payload = route.request().postDataJSON();
    return route.fulfill({ status: 201, json: replay() });
  });
  await page.goto("/");
  await expect(page.getByText("Trading day", { exact: true })).toBeVisible();
  await expect(page.getByText("Calendar month", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Start blind replay" }),
  ).toBeDisabled();
  await expect(page.getByText("Friday, Sep 18, 2026")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "19", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "7", exact: true }),
  ).toBeDisabled();
  await page.getByRole("combobox", { name: "Stock" }).fill("NV");
  await expect(page.getByText("Forming that day")).toBeVisible();
  await page.getByRole("combobox", { name: "Stock" }).press("ArrowDown");
  await page.getByRole("combobox", { name: "Stock" }).press("Enter");
  await expect(page.getByText("Selected: NVDA")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Start blind replay" }),
  ).toBeEnabled();
  await expect(
    page.getByText("Morning research · 8:30 AM–10:00 AM CT"),
  ).toBeVisible();
  await expect(page.getByLabel("Replay start")).toHaveCount(0);
  await page.screenshot({
    path: "../docs/images/strategy-lab-replay-create.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Start blind replay" }).click();
  expect(payload).toMatchObject({
    start: "08:30",
    end: "10:00",
    market_date: "2026-09-18",
    instrument: "NVDA",
  });
});

test("random case uses only the selected historical universe without outcome requests", async ({
  page,
}) => {
  const requested = [];
  page.on("request", (request) => requested.push(request.url()));
  await mockCreationData(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Pick random case" }).click();
  const selected = await page.locator(".combobox-field small").textContent();
  expect(universe.symbols).toContain(selected.replace("Selected: ", ""));
  expect(
    requested.some((url) => /outcome|return|mfe|mae/i.test(url)),
  ).toBeFalsy();
});

test("private historical baseline shows denominators and episode drilldown", async ({
  page,
}) => {
  await mockCreationData(page);
  const metric = {
    percentage: 67.0,
    numerator: 59,
    denominator: 88,
    insufficient: 8,
    median_percent: 0.43,
  };
  await page.route("**/api/internal/strategy-lab/baseline", (route) =>
    route.fulfill({
      json: {
        id: 4,
        status: "COMPLETED",
        period: { start: "2026-08-19", end: "2026-09-18" },
        strategy_version: "experimental-forming-v1/abc123",
        coverage: {
          trading_days: 20,
          trading_days_completed: 20,
          symbols_evaluated: 94,
          eligible_evaluations: 2820,
          symbol_failures: 2,
          limitations: [],
        },
        forming_long: {
          episodes: 96,
          bars_3: metric,
          bars_5: metric,
          bars_10: metric,
          median_favorable_excursion_percent: 1.2,
          median_adverse_excursion_percent: -0.4,
        },
        forming_short: {
          episodes: 12,
          bars_3: metric,
          bars_5: metric,
          bars_10: metric,
          median_favorable_excursion_percent: 0.9,
          median_adverse_excursion_percent: -0.3,
        },
      },
    }),
  );
  await page.route(
    "**/api/internal/strategy-lab/baseline/episodes?**",
    (route) =>
      route.fulfill({
        json: {
          items: [
            {
              id: 1,
              symbol: "AMD",
              market_date: "2026-09-18",
              setup_state: "FORMING_LONG",
              observation_price: 100,
              return_after_3_bars: 0.004325,
              return_after_5_bars: -0.003475,
              return_after_10_bars: null,
              maximum_favorable_excursion: 0.01,
              maximum_adverse_excursion: -0.005,
            },
          ],
        },
      }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Historical baseline" }).click();
  await expect(
    page.getByRole("heading", { name: "Historical Strategy Baseline" }),
  ).toBeVisible();
  await expect(
    page.getByText("59 / 88 eligible · 8 insufficient").first(),
  ).toBeVisible();
  await expect(page.getByText("+0.43%").last()).toBeVisible();
  await expect(page.getByText("-0.35%")).toBeVisible();
  await expect(page.getByText(/not a win rate/i)).toBeVisible();
});

test("all missing-universe sessions are reported as unavailable coverage", async ({
  page,
}) => {
  await mockCreationData(page);
  await page.route("**/api/internal/strategy-lab/baseline", (route) =>
    route.fulfill({
      json: {
        id: 1,
        status: "INCOMPLETE",
        period: { start: "2026-08-21", end: "2026-09-18" },
        strategy_version: "experimental-forming-v1/b067b3150de3",
        coverage: {
          trading_days: 20,
          trading_days_completed: 20,
          trading_sessions_requested: 20,
          trading_sessions_processed: 20,
          sessions_with_universe_coverage: 0,
          sessions_missing_universe: 20,
          symbols_evaluated: 0,
          eligible_evaluations: 0,
          symbol_failures: 0,
          limitations: [],
        },
        forming_long: { episodes: 0, bars_3: {}, bars_5: {}, bars_10: {} },
        forming_short: { episodes: 0, bars_3: {}, bars_5: {}, bars_10: {} },
      },
    }),
  );
  await page.route(
    "**/api/internal/strategy-lab/baseline/episodes?**",
    (route) => route.fulfill({ json: { items: [] } }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Historical baseline" }).click();
  await expect(
    page.getByRole("heading", { name: "Historical universe unavailable" }),
  ).toBeVisible();
  await expect(
    page.getByText(/does not contain sufficient historical universe coverage/i),
  ).toBeVisible();
  await expect(page.getByText("Sessions with universe")).toBeVisible();
  await expect(page.getByText("Sessions missing universe")).toBeVisible();
});

test("custom equity time, empty-universe manual fallback, and futures separation", async ({
  page,
}) => {
  await mockCreationData(page, {
    trading_date: "2026-09-18",
    recorded: false,
    symbols: [],
    groups: [],
  });
  await page.goto("/");
  await expect(
    page.getByText("No scanner universe was recorded for this date."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Enter symbol manually" }).click();
  await page.getByLabel("Stock symbol").fill("aapl");
  await expect(page.getByLabel("Stock symbol")).toHaveValue("AAPL");
  await page.getByRole("button", { name: "Customize time" }).click();
  await page.getByLabel("Replay start").fill("09:00");
  await expect(page.getByLabel("Replay start")).toHaveValue("09:00");
  await page.getByLabel("Asset").selectOption("FUTURE");
  await expect(page.getByLabel("Instrument")).toHaveValue("MES");
  await expect(page.getByRole("combobox", { name: "Stock" })).toHaveCount(0);
  await expect(
    page.getByText(/compatible historical-data provider/),
  ).toBeVisible();
  await expect(page.getByLabel("Replay start")).toHaveValue("08:00");
});
