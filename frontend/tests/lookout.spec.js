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
  await expect(page.locator(".lookout-group")).toHaveCount(1);
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
  await expect(page.locator(".lookout-group")).toHaveCount(1);
  await expect(page.locator(".lookout-count")).toHaveText("5");
  await page.locator(".lookout-row").click();
  await expect(page.locator("tbody tr")).toHaveCount(5);
  await expect(page.locator("tbody tr").first()).toContainText("No-Go $175.00");
  await expect(page.locator("tbody tr").last()).toContainText("9:47 AM ET");
  await expect(page.locator(".lookout-plan")).toContainText(plan);
  const filters = page.getByRole("group", { name: "Alert category" });
  await filters.getByRole("button", { name: "Long", exact: true }).click();
  await expect(page.locator(".lookout-group")).toHaveCount(1);
  await expect(page.locator(".lookout-group")).toContainText("LONG LOOKOUT");
  await filters.getByRole("button", { name: "Short", exact: true }).click();
  await expect(page.locator(".lookout-group")).toHaveCount(1);
  await expect(page.locator(".lookout-group")).toContainText("SHORT LOOKOUT");
  await filters.getByRole("button", { name: "Levels", exact: true }).click();
  await expect(page.locator(".lookout-count")).toHaveText("3");
  await filters.getByRole("button", { name: "All", exact: true }).click();
  await page.getByLabel("Alerts date").fill("2026-10-02");
  await expect(page.locator(".lookout-group")).toHaveCount(1);
  await expect(page.locator(".lookout-group")).toContainText("Support $175.00");
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
  await expect(page.locator(".lookout-count")).toHaveText("3");
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
  await expect(page.locator(".lookout-group")).toContainText("Support $175.00");
  feeds["2026-10-02"].unshift(alert(11, "LONG", "2026-10-02"));
  await poll(page);
  await expect(page.locator(".lookout-count")).toHaveText("2");
  expect(await count(page)).toBe(0);
  feeds[day].unshift(alert(12));
  await page.getByLabel("Alerts date").fill(day);
  await expect(page.locator(".lookout-count")).toHaveText("2");
  expect(await count(page)).toBe(0);
  feeds[day].unshift(alert(13));
  await poll(page);
  await expect(page.locator(".lookout-count")).toHaveText("3");
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
  await expect(page.locator(".lookout-count")).toHaveText("2");
  expect(await count(page)).toBe(1);
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "Dashboard", exact: true })
    .click();
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "Alerts", exact: true })
    .click();
  await expect(page.locator(".lookout-count")).toHaveText("2");
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
  await expect(page.locator(".lookout-count")).toHaveText("2");
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
  await expect(page.locator(".lookout-group")).toContainText(
    "LONG LOOKOUT $175.00",
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
  await expect(page.locator(".lookout-count")).toHaveText("2");
  expect(await count(page)).toBe(0);
});

test("grouped history remains readable on desktop and narrow screens", async ({
  page,
}, info) => {
  await setup(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.locator(".lookout-row").click();
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
  await page.screenshot({
    path: info.outputPath("lookout-alerts-mobile.png"),
    fullPage: true,
  });
});

test("distinct IDs, timestamp ordering, accordion keyboard, missing fields and live expansion", async ({
  page,
}) => {
  const { feeds } = await setup(page);
  const older = {
    ...alert(2, "SUPPORT"),
    trigger_level: null,
    timestamp: `${day}T13:21:00Z`,
    price: null,
  };
  feeds[day] = [
    older,
    older,
    { ...alert(3, "RESISTANCE"), symbol: "DELL", game_plan: null },
    alert(1),
  ];
  await poll(page);
  await expect(page.locator(".lookout-group")).toHaveCount(2);
  await expect(page.locator(".lookout-row").first()).toContainText("DELL");
  const cbrs = page.locator(".lookout-row").filter({ hasText: "CBRS" });
  await expect(cbrs.locator(".lookout-count")).toHaveText("2");
  await cbrs.focus();
  await page.keyboard.press("Enter");
  await expect(cbrs).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator("tbody tr").first()).toContainText(
    "LONG LOOKOUT $175.00",
  );
  await expect(page.locator("tbody tr").first()).toContainText("$175.12");
  await expect(page.locator("tbody tr").last().locator("td").last()).toHaveText(
    "—",
  );
  await expect(page.locator("tbody tr").last()).toContainText("Support —");
  await expect(page.getByText(plan, { exact: true })).toHaveCount(1);
  await poll(page);
  await expect(cbrs).toHaveAttribute("aria-expanded", "true");
  feeds[day].unshift({ ...alert(4), timestamp: `${day}T13:59:00Z` });
  await poll(page);
  await expect(page.locator(".lookout-row").first()).toContainText("CBRS");
  await expect(cbrs.locator(".lookout-count")).toHaveText("3");
  await expect(page.locator("tbody tr")).toHaveCount(3);
  await page.locator(".lookout-row").filter({ hasText: "DELL" }).click();
  await expect(cbrs).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByText("Original Game Plan unavailable.")).toBeVisible();
  await page.locator(".lookout-row").filter({ hasText: "DELL" }).click();
  await expect(page.locator("tbody tr")).toHaveCount(0);
  await cbrs.click();
  await page
    .getByRole("group", { name: "Alert category" })
    .getByRole("button", { name: "Short", exact: true })
    .click();
  await expect(page.locator(".lookout-group")).toHaveCount(0);
  await expect(
    page.getByText("No Short lookout alerts for this date."),
  ).toBeVisible();
});

test("complete cursor pagination is silent and refresh stops at cached history", async ({
  page,
}) => {
  await setup(page);
  let requests = [];
  await page.route("**/api/alerts?**", (route) => {
    const url = new URL(route.request().url());
    const cursor = url.searchParams.get("before_id");
    requests.push(cursor);
    return route.fulfill({
      json: {
        items: cursor ? [alert(3), alert(2), alert(1)] : [alert(5), alert(4)],
        next_before_id: cursor ? null : 4,
      },
    });
  });
  // A different date starts a fresh complete load, rather than the live overlap path.
  await page.getByLabel("Alerts date").fill("2026-10-02");
  await page.getByLabel("Alerts date").fill(day);
  await expect(page.locator(".lookout-count")).toHaveText("5");
  expect(requests).toContain("4");
  await page.getByRole("button", { name: "Sound Off", exact: true }).click();
  requests = [];
  await poll(page);
  await expect(page.locator(".lookout-count")).toHaveText("5");
  expect(requests).toEqual([null]);
  expect(await count(page)).toBe(0);
});

test("refresh errors preserve complete history and expansion", async ({
  page,
}) => {
  await setup(page);
  await page.locator(".lookout-row").click();
  await page.route("**/api/alerts?**", (route) =>
    route.fulfill({ status: 500, json: {} }),
  );
  await poll(page);
  await expect(page.getByRole("alert")).toContainText(
    "Cannot load complete lookout history",
  );
  await expect(page.locator(".lookout-count")).toHaveText("1");
  await expect(page.locator(".lookout-row")).toHaveAttribute(
    "aria-expanded",
    "true",
  );
});

test("live burst follows multiple new pages before overlap and sounds once", async ({
  page,
}) => {
  await setup(page);
  await page.locator(".lookout-row").click();
  await page.getByRole("button", { name: "Sound Off", exact: true }).click();
  await page.route("**/api/alerts?**", (route) => {
    const cursor = new URL(route.request().url()).searchParams.get("before_id");
    return route.fulfill({
      json: {
        items: cursor ? [alert(3), alert(2), alert(1)] : [alert(5), alert(4)],
        next_before_id: cursor ? null : 4,
      },
    });
  });
  await poll(page);
  await expect(page.locator(".lookout-count")).toHaveText("5");
  await expect(page.locator("tbody tr")).toHaveCount(5);
  expect(await count(page)).toBe(1);
  await poll(page);
  expect(await count(page)).toBe(1);
});

test("bounded incomplete pagination never publishes partial counts", async ({
  page,
}) => {
  await setup(page);
  let calls = 0;
  await page.route("**/api/alerts?**", (route) => {
    calls++;
    return route.fulfill({
      json: { items: [alert(100 - calls)], next_before_id: 100 - calls },
    });
  });
  await poll(page);
  await expect(page.getByRole("alert")).toContainText(
    "Cannot load complete lookout history",
  );
  expect(calls).toBe(20);
  await expect(page.locator(".lookout-count")).toHaveText("1");
});
