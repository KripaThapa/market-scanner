import { test, expect } from "@playwright/test";

const day = "2026-10-05";
const plan =
  "Tenet Swing | 1 HR MTF Setup, No go under 173, Long over 175 holds";
const alert = (id, type = "LONG", date = day) => ({
  id,
  symbol: "CBRS",
  timestamp: `${date}T13:47:00Z`,
  trading_date: date,
  alert_type: `WATCHLIST_LEVEL_${type}`,
  direction: ["LONG", "SHORT"].includes(type) ? type : "LEVEL",
  level_type: type,
  trigger_level: "175.00000000",
  price: 175.12,
  game_plan: plan,
  support_pivots: ["173"],
  resistance_pivots: ["177", "175"],
});

async function setup(page, { preference, blocked = false } = {}) {
  await page.clock.install({ time: new Date(`${day}T14:00:00Z`) });
  await page.addInitScript(
    ({ preference, blocked }) => {
      if (preference) localStorage.setItem("watchlistLookoutSound", preference);
      window.tones = 0;
      window.audioResumes = 0;
      class Audio {
        state = "running";
        currentTime = 0;
        destination = {};
        async resume() {
          window.audioResumes++;
          if (blocked) throw new Error("blocked");
        }
        async close() {}
        createOscillator() {
          return {
            frequency: { setValueAtTime() {} },
            connect() {},
            disconnect() {},
            start() {
              window.tones++;
            },
            stop() {},
          };
        }
        createGain() {
          return {
            gain: {
              setValueAtTime() {},
              linearRampToValueAtTime() {},
              exponentialRampToValueAtTime() {},
            },
            connect() {},
            disconnect() {},
          };
        }
      }
      window.AudioContext = Audio;
    },
    { preference, blocked },
  );
  await page.route("**/api/dashboard", (route) =>
    route.fulfill({
      json: {
        state: { status: "idle" },
        counts: {},
        universe: [],
        setups: [],
        alerts: [],
        sectors: [],
      },
    }),
  );
  const feeds = {
    [day]: [alert(1)],
    "2026-10-02": [alert(10, "SUPPORT", "2026-10-02")],
  };
  const requests = [];
  await page.route("**/api/alerts?**", (route) => {
    const url = new URL(route.request().url());
    const selected = url.searchParams.get("trading_date");
    requests.push(selected);
    return route.fulfill({
      json: {
        items: feeds[selected] || [],
        trading_date: selected,
        next_before_id: null,
      },
    });
  });
  await page.goto("/");
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "Alerts", exact: true })
    .click();
  await expect(page.locator(".lookout-alert")).toHaveCount(1);
  return { feeds, requests };
}
const count = (page) => page.evaluate(() => window.tones);
async function poll(page) {
  await page.clock.fastForward(15000);
  // Ensure fetch callbacks have completed before the next virtual-clock tick.
  await page.evaluate(
    () => new Promise((resolve) => requestAnimationFrame(resolve)),
  );
}

test("date, categories, ET time, original Game Plan and FORMING exclusion", async ({
  page,
}) => {
  const { feeds } = await setup(page);
  feeds[day] = [
    alert(5, "NO_GO"),
    alert(4, "SHORT"),
    alert(3, "SUPPORT"),
    alert(2, "RESISTANCE"),
    alert(1),
    { ...alert(6), alert_type: "FORMING_LONG" },
    alert(7, "LONG", "2026-10-02"),
  ];
  await poll(page);
  await expect(page.locator(".lookout-alert")).toHaveCount(5);
  await expect(page.locator(".lookout-alert").first()).toContainText(
    "No-Go level crossed below",
  );
  await expect(page.locator(".lookout-alert").last()).toContainText(
    "9:47 AM ET",
  );
  await expect(page.locator(".lookout-alert").last()).toContainText(plan);
  await expect(page.locator(".lookout-alert").last()).toContainText(
    "Resistance: $177.00 / $175.00",
  );
  const filters = page.getByRole("group", { name: "Alert category" });
  await filters.getByRole("button", { name: "Long", exact: true }).click();
  await expect(page.locator(".lookout-alert")).toHaveCount(1);
  await expect(page.locator(".lookout-alert")).toContainText("LONG LOOKOUT");
  await filters.getByRole("button", { name: "Short", exact: true }).click();
  await expect(page.locator(".lookout-alert")).toHaveCount(1);
  await expect(page.locator(".lookout-alert")).toContainText("SHORT LOOKOUT");
  await filters.getByRole("button", { name: "Levels", exact: true }).click();
  await expect(page.locator(".lookout-alert")).toHaveCount(3);
  await filters.getByRole("button", { name: "All", exact: true }).click();
  await page.getByLabel("Alerts date").fill("2026-10-02");
  await expect(page.locator(".lookout-alert")).toHaveCount(1);
  await expect(page.locator(".lookout-alert")).toContainText(
    "Trading date: 2026-10-02",
  );
  await expect(
    page.getByText("Historical alerts · sound is disabled for this date."),
  ).toBeVisible();
});

test("initial load is silent; one tone for new persisted live IDs; repeats and filters stay silent", async ({
  page,
}) => {
  const { feeds } = await setup(page);
  await page.getByRole("button", { name: "Sound Off", exact: true }).click();
  expect(await count(page)).toBe(0);
  await poll(page);
  expect(await count(page)).toBe(0);
  feeds[day].unshift(alert(3, "SHORT"), alert(2));
  await poll(page);
  await expect(page.locator(".lookout-alert")).toHaveCount(3);
  expect(await count(page)).toBe(1);
  await poll(page);
  expect(await count(page)).toBe(1);
  await page
    .getByRole("group", { name: "Alert category" })
    .getByRole("button", { name: "Long", exact: true })
    .click();
  await poll(page);
  expect(await count(page)).toBe(1);
  await page.getByRole("button", { name: "Sound On", exact: true }).click();
  feeds[day].unshift(alert(4));
  await poll(page);
  expect(await count(page)).toBe(1);
  expect(
    await page.evaluate(() => localStorage.getItem("watchlistLookoutSound")),
  ).toBe("off");
});

test("historical browsing never sounds, returning today establishes a silent baseline", async ({
  page,
}) => {
  const { feeds } = await setup(page);
  await page.getByRole("button", { name: "Sound Off", exact: true }).click();
  await page.getByLabel("Alerts date").fill("2026-10-02");
  await expect(page.locator(".lookout-alert")).toContainText("2026-10-02");
  feeds["2026-10-02"].unshift(alert(11, "LONG", "2026-10-02"));
  await poll(page);
  await expect(page.locator(".lookout-alert")).toHaveCount(2);
  expect(await count(page)).toBe(0);
  feeds[day].unshift(alert(12));
  await page.getByLabel("Alerts date").fill(day);
  await expect(page.locator(".lookout-alert")).toHaveCount(2);
  expect(await count(page)).toBe(0);
  feeds[day].unshift(alert(13));
  await poll(page);
  await expect(page.locator(".lookout-alert")).toHaveCount(3);
  expect(await count(page)).toBe(1);
});

test("saved sound preference is restored but existing alerts never replay", async ({
  page,
}) => {
  const { feeds } = await setup(page, { preference: "on" });
  await expect(
    page.getByRole("button", { name: "Sound On", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  expect(await count(page)).toBe(0);
  expect(await page.evaluate(() => window.audioResumes)).toBe(0);
  await page.getByRole("button", { name: "Enable audio in this tab" }).click();
  feeds[day].unshift(alert(2));
  await poll(page);
  await expect(page.locator(".lookout-alert")).toHaveCount(2);
  expect(await count(page)).toBe(1);
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "Dashboard", exact: true })
    .click();
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "Alerts", exact: true })
    .click();
  await expect(page.locator(".lookout-alert")).toHaveCount(2);
  await page.getByRole("button", { name: "Enable audio in this tab" }).click();
  await poll(page);
  expect(await count(page)).toBe(1);
});

test("autoplay/audio failures keep visual alerts working", async ({ page }) => {
  const { feeds } = await setup(page, { blocked: true });
  await page.getByRole("button", { name: "Sound Off", exact: true }).click();
  await expect(
    page.getByText(
      "Sound is unavailable in this browser. Visual alerts remain active.",
    ),
  ).toBeVisible();
  feeds[day].unshift(alert(2));
  await poll(page);
  await expect(page.locator(".lookout-alert")).toHaveCount(2);
  expect(await count(page)).toBe(0);
});

test("date-following advances at New York midnight without sounding the new baseline", async ({
  page,
}) => {
  const { feeds, requests } = await setup(page);
  await page.getByRole("button", { name: "Sound Off", exact: true }).click();
  feeds["2026-10-06"] = [alert(20, "LONG", "2026-10-06")];
  await page.clock.setSystemTime(new Date("2026-10-06T04:00:01Z"));
  await poll(page);
  await expect(page.getByLabel("Alerts date")).toHaveValue("2026-10-06");
  await expect(page.locator(".lookout-alert")).toContainText(
    "Trading date: 2026-10-06",
  );
  expect(requests).toContain("2026-10-06");
  expect(await count(page)).toBe(0);
});

test("stored Sound Off remains silent as live IDs arrive", async ({ page }) => {
  const { feeds } = await setup(page, { preference: "off" });
  await expect(
    page.getByRole("button", { name: "Sound Off", exact: true }),
  ).toHaveAttribute("aria-pressed", "false");
  feeds[day].unshift(alert(2));
  await poll(page);
  await expect(page.locator(".lookout-alert")).toHaveCount(2);
  expect(await count(page)).toBe(0);
});

test("lookout cards remain readable on desktop and narrow screens", async ({
  page,
}, info) => {
  await setup(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await expect(page.locator(".lookout-plan")).toContainText(plan);
  await page.screenshot({
    path: info.outputPath("lookout-alerts-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByLabel("Alerts date")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Sound Off", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
});
