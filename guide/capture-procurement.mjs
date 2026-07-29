// Procurement Planning guide — screenshot capture (drives the demo instance).
//   node capture-procurement.mjs         # needs the :8001 demo server running
// Output: ./screenshots-procurement/<NN-name>.png
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.BASE || "http://127.0.0.1:8001";
const PW = process.env.DEMO_PW || "planet-demo";
const OUT = path.resolve("screenshots-procurement");
fs.mkdirSync(OUT, { recursive: true });

let seq = 0;
const failures = [];

async function settle(page, ms = 800) {
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(ms);
}
async function shot(page, name) {
  seq += 1;
  const f = path.join(OUT, `${String(seq).padStart(2, "0")}-${name}.png`);
  await settle(page);
  await page.screenshot({ path: f, fullPage: true });
  console.log("  ✓ " + path.basename(f));
}
async function login(page, u) {
  await page.context().clearCookies();
  await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: /sign in/i }).waitFor({ timeout: 15000 });
  await page.locator("form input").nth(0).fill(u);
  await page.locator('input[type="password"]').fill(PW);
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.getByText("SAND PLANET").waitFor({ timeout: 15000 });
  await settle(page);
}
async function group(page, label) {
  await page.getByRole("button", { name: label }).first().click();
  await settle(page);
}
async function step(page, name, fn) {
  try { await fn(); await shot(page, name); }
  catch (e) {
    failures.push(`${name}: ${e.message.split("\n")[0]}`);
    console.log("  ✗ " + name + " — " + e.message.split("\n")[0]);
  }
}
async function openSchedule(page) {
  await group(page, "Planning");
  await page.getByText(/PSC-SJR/).first().click();
  await settle(page, 1000);
}

async function main() {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1680, height: 1050 } });
  const page = await ctx.newPage();
  page.setDefaultTimeout(9000);

  console.log("[director]");
  await login(page, "director");
  await step(page, "planning-list", () => group(page, "Planning"));
  await step(page, "schedule-detail", () => openSchedule(page));
  await step(page, "quotes-panel", async () => {
    const row = page.getByRole("row").filter({ hasText: /heat pumps/i });
    await row.getByRole("button", { name: "Quotes" }).first().click();
    await settle(page, 900);
  });
  await login(page, "director");
  await step(page, "track-panel", async () => {
    await openSchedule(page);
    const row = page.getByRole("row").filter({ hasText: /Sand media filters/i });
    await row.getByRole("button", { name: "Track" }).first().click();
    await settle(page, 900);
  });
  await login(page, "director");
  await step(page, "new-line", async () => {
    await openSchedule(page);
    await page.getByRole("button", { name: /Add line/i }).first().click();
    await settle(page, 700);
  });

  // Purchasing view (confirms commercials) — same detail, its own login
  console.log("[purchasing]");
  await login(page, "purchasing");
  await step(page, "schedule-purchasing", () => openSchedule(page));

  // Site engineer — value columns hidden (reached via the project tab)
  console.log("[eng]");
  await login(page, "eng");
  await step(page, "schedule-site-noprices", async () => {
    await page.getByRole("button", { name: /Open project/i }).first().click();
    await settle(page, 600);
    await page.getByRole("button", { name: "Procurement", exact: true }).first().click();
    await settle(page, 1000);
  });

  await ctx.close();
  await browser.close();
  console.log(`\nCaptured ${seq} shots to ${OUT}`);
  if (failures.length) {
    console.log(`\n${failures.length} issue(s):`);
    failures.forEach((f) => console.log("  - " + f));
    process.exitCode = 1;
  }
}
main();
