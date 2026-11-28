import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const API = `http://localhost:${process.env.E2E_API_PORT ?? 8021}`;
const PASSWORD = "e2e-citizen-pass-1";
const STAFF_PASSWORD = "e2e-admin-pass";
let n = 0;
const uniq = () => `${Date.now()}${n++}`;

const HOUSEHOLD = {
  monthly_kwh: 300, members: 4, lpg_cylinders_per_month: 1, commute_mode: "two_wheeler", commute_km_per_day: 8,
  home_type: "apartment", ac_count: 2, has_geyser: true, has_washing_machine: true, has_ev: false, has_solar: true,
  roof_area_sqm: 40, discom: "ugvcl", area: "urban",
};

async function citizenWithMeter(request: APIRequestContext, extra: Record<string, unknown> = {}) {
  const email = `meter${uniq()}@example.com`;
  const reg = await request.post(`${API}/api/auth/register`, { data: { email, password: PASSWORD, name: "Meter Home", district_id: 1, ward: "Ward 3" } });
  expect(reg.status()).toBe(201);
  const { token } = await reg.json();
  const auth = { Authorization: `Bearer ${token}` };
  expect((await request.put(`${API}/api/household`, { headers: auth, data: { ...HOUSEHOLD, ...extra } })).status()).toBe(200);
  const live = await request.get(`${API}/api/meter/live`, { headers: auth });
  expect(live.status()).toBe(200);
  return { email, token, auth, feeder: (await live.json()).meter.feeder as string };
}

async function signIn(page: Page, email: string, password = STAFF_PASSWORD) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel(/^Password/).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("DISCOM staff land on their own console; GEDA, households and signed-out visitors are kept apart", async ({ page, request }) => {
  await signIn(page, "engineer@example.com");
  await expect(page).toHaveURL(/\/discom$/);
  await expect(page.getByRole("heading", { name: "Overview", level: 1 })).toBeVisible();
  await expect(page.getByText("Uttar Gujarat Vij Company (UGVCL)")).toBeVisible();
  for (const [link, heading] of [["Feeders", "Feeders"], ["Anomalies", "Anomalies"], ["Outages", "Outages"], ["Solar requests", "Solar requests"]] as const) {
    await page.getByRole("link", { name: new RegExp(`^${link}`) }).first().click();
    await expect(page.getByRole("heading", { name: heading, level: 1 })).toBeVisible();
  }
  // DISCOM staff never see GEDA's console: it sends them back to their own.
  await page.goto("/geda");
  await expect(page).toHaveURL(/\/discom$/);

  const c = await citizenWithMeter(request);
  await page.evaluate((t) => { localStorage.clear(); localStorage.setItem("nidhi.token", t); }, c.token);
  await page.goto("/discom");
  await expect(page).toHaveURL(/\/$/); // households use the app

  await page.evaluate(() => localStorage.clear());
  await page.goto("/discom");
  await expect(page).toHaveURL(/\/login$/);
});

test("overview counts the meters, labels simulated ones and draws the curve", async ({ page, request }) => {
  await citizenWithMeter(request);
  await citizenWithMeter(request);
  await signIn(page, "auditor@example.com");
  await expect(page).toHaveURL(/\/discom$/);
  await expect(page.getByText(/\d+ of \d+ meters are simulated for this demo/)).toBeVisible();
  await expect(page.getByText("Demand now")).toBeVisible();
  await expect(page.getByRole("img", { name: /Demand and rooftop solar/ })).toBeVisible();
  await page.getByRole("link", { name: /^Feeders/ }).first().click();
  await expect(page.getByRole("row").nth(1)).toContainText(/UGVCL-/);
});

test("an engineer plans an outage and the household sees it; an auditor can only read", async ({ page, request }) => {
  const home = await citizenWithMeter(request);
  await signIn(page, "engineer@example.com");
  await page.getByRole("link", { name: /^Outages/ }).first().click();
  await page.getByLabel("Feeder").selectOption(home.feeder);
  await page.getByLabel("Reason").fill("Transformer maintenance e2e");
  const day = new Date(Date.now() + 2 * 86_400_000).toISOString().slice(0, 10);
  await page.getByLabel("From").fill(`${day}T10:00`);
  await page.getByLabel("Until").fill(`${day}T12:00`);
  await page.getByRole("button", { name: "Notify households" }).click();
  await expect(page.getByText("Transformer maintenance e2e").first()).toBeVisible();
  await expect(page.getByText(/homes notified/).first()).toBeVisible();

  const live = await (await request.get(`${API}/api/meter/live`, { headers: home.auth })).json();
  expect(live.outages.map((o: { reason: string }) => o.reason)).toContain("Transformer maintenance e2e");
  const notes = await (await request.get(`${API}/api/notifications`, { headers: home.auth })).json();
  expect(notes.unread).toBeGreaterThan(0);

  // Cancel it again (its own row: the demo data has outages of its own on other feeders).
  await page.getByRole("listitem").filter({ hasText: "Transformer maintenance e2e" }).getByRole("button", { name: "Cancel outage" }).click();
  await expect(page.getByText("Transformer maintenance e2e")).toHaveCount(0);

  // An auditor sees the page but not the form.
  await page.evaluate(() => localStorage.clear());
  await signIn(page, "auditor@example.com");
  await page.getByRole("link", { name: /^Outages/ }).first().click();
  await expect(page.getByText("This account can view outages but not plan them.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Notify households" })).toHaveCount(0);
});

test("a bill that disagrees with the meter shows up as an anomaly and an engineer resolves it", async ({ page, request }) => {
  const home = await citizenWithMeter(request);
  await request.post(`${API}/api/readings`, { headers: home.auth, data: { month: "2026-10", kwh: 900 } });
  const bill = await (await request.get(`${API}/api/meter/bill`, { headers: home.auth })).json();
  expect(bill.mismatch).toBe(true);
  await signIn(page, "engineer@example.com");
  await page.getByRole("link", { name: /^Anomalies/ }).first().click();
  await expect(page.getByText("Bill and meter disagree").first()).toBeVisible();
  await expect(page.getByText(/Meter NID\d+/).first()).toBeVisible();
  // No name or email of the household on the page.
  await expect(page.locator("body")).not.toContainText(home.email);
  await expect(page.locator("body")).not.toContainText("Meter Home");
  const before = await page.getByRole("button", { name: "Mark resolved" }).count();
  await page.getByRole("button", { name: "Mark resolved" }).first().click();
  await expect(page.getByRole("button", { name: "Mark resolved" })).toHaveCount(before - 1);
});

test("the console reads in Gujarati and Hindi", async ({ page }) => {
  await signIn(page, "engineer@example.com");
  await expect(page.getByRole("heading", { name: "Overview", level: 1 })).toBeVisible();
  // The selector's own label is translated too, so find it by role: an engineer sees only the language picker.
  const language = page.getByRole("combobox");
  await language.selectOption("gu");
  await expect(page.getByRole("heading", { name: "ઝાંખી", level: 1 })).toBeVisible();
  await language.selectOption("hi");
  await expect(page.getByRole("heading", { name: "अवलोकन", level: 1 })).toBeVisible();
  await page.getByRole("link", { name: /^फ़ीडर/ }).first().click();
  await expect(page.getByRole("heading", { name: "फ़ीडर", level: 1 })).toBeVisible();
});

test("the console fits a phone: pages scroll as a tab bar and nothing overflows sideways", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await signIn(page, "engineer@example.com");
  await expect(page.getByRole("heading", { name: "Overview", level: 1 })).toBeVisible();
  for (const path of ["/discom", "/discom/feeders", "/discom/anomalies", "/discom/outages", "/discom/leads"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, `${path} scrolls sideways by ${overflow}px`).toBeLessThanOrEqual(1);
  }
});

test("a judge can open either console from the demo buttons, read-only, with no sign-up", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByText("demo-discom@example.com").first()).toBeVisible();
  await page.getByRole("button", { name: "DISCOM console" }).click();
  await expect(page.getByLabel("Email")).toHaveValue("demo-discom@example.com");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/discom$/);
  await page.getByRole("link", { name: /^Outages/ }).first().click();
  await expect(page.getByText("This account can view outages but not plan them.")).toBeVisible();

  await page.evaluate(() => localStorage.clear());
  await page.goto("/login");
  await page.getByRole("button", { name: "GEDA console" }).click();
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/geda$/);
  await expect(page.getByRole("heading", { name: "Overview", level: 1 })).toBeVisible();
});

test("the landing page shows the demo household login", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText(/demo-household@example\.com/).first()).toBeVisible();
});
