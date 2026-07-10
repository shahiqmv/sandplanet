// Planet User Guide — screenshot capture (PLANET-UG-01).
//
// Drives the ISOLATED demo instance (default http://127.0.0.1:8001, the
// --settings=config.settings_demo server) through the real SPA, logging in
// per role and screenshotting every buildable screen + filled document.
// It never touches the live :8000 tunnel.
//
//   node capture.mjs               # all roles, desktop + mobile
//   node capture.mjs --only=pm     # just one role (dev loop)
//   BASE=http://127.0.0.1:8001 node capture.mjs
//
// Output: ./screenshots/<NN-name>.png  (numbered so guide order is stable)

import { chromium, devices } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.BASE || "http://127.0.0.1:8001";
const PW = process.env.DEMO_PW || "planet-demo";
const OUT = path.resolve("screenshots");
const only = (process.argv.find((a) => a.startsWith("--only=")) || "").split("=")[1];

fs.mkdirSync(OUT, { recursive: true });

let seq = 0;
const failures = [];

// ---- low-level helpers ---------------------------------------------------

async function settle(page, ms = 700) {
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(ms);
}

async function shot(page, name) {
  seq += 1;
  const file = path.join(OUT, `${String(seq).padStart(2, "0")}-${name}.png`);
  await settle(page);
  await page.screenshot({ path: file, fullPage: true });
  console.log(`  ✓ ${path.basename(file)}`);
}

async function login(page, username) {
  await page.context().clearCookies();  // force the login screen even on re-login
  await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: /sign in/i }).waitFor({ timeout: 15000 });
  await page.locator("form input").nth(0).fill(username);
  await page.locator('input[type="password"]').fill(PW);
  await page.getByRole("button", { name: /sign in/i }).click();
  // header appears once authenticated
  await page.getByText("SAND PLANET").waitFor({ timeout: 15000 });
  await settle(page);
}

// Click a top-level nav group ("Procurement", "Finance", "People", ...).
// Non-exact: the "My Tasks" group carries a pending-count badge in its name.
async function group(page, label) {
  await page.getByRole("button", { name: label }).first().click();
  await settle(page);
}

// Click a register/tab button by its exact short label ("PR", "LM", ...).
async function tab(page, label) {
  await page.getByRole("button", { name: label, exact: true }).first().click();
  await settle(page);
}

// Click any element containing this text (for non-anchor clickables).
async function clickText(page, text) {
  await page.getByText(text, { exact: false }).first().click();
  await settle(page);
}

// Click a sub-tab ghost button ("Items", "Suppliers", "Portfolio", ...).
async function subtab(page, label) {
  await page.getByRole("button", { name: label, exact: true }).first().click();
  await settle(page);
}

// From the Sites list, open a site by its name.
async function openSite(page, name = "Soneva Jani") {
  // If not on the sites list, go there first.
  const row = page.getByText(name, { exact: false }).first();
  await row.click();
  await settle(page);
}

// Open a document view from any register/dashboard by its exact ref link.
async function openRef(page, ref) {
  await page.getByRole("link", { name: ref, exact: true }).first().click();
  await settle(page);
}

async function clickButton(page, name) {
  await page.getByRole("button", { name, exact: false }).first().click();
  await settle(page);
}

// Run one shot, logging (not throwing) on failure so the run continues.
async function step(page, name, fn) {
  try {
    await fn();
    await shot(page, name);
  } catch (e) {
    failures.push(`${name}: ${e.message.split("\n")[0]}`);
    console.log(`  ✗ ${name} — ${e.message.split("\n")[0]}`);
  }
}

// ---- the shot list, grouped by role -------------------------------------

async function run(browser, roleKey, fn, { mobile = false } = {}) {
  if (only && only !== roleKey) return;
  const context = await browser.newContext(
    mobile ? devices["Pixel 7"] : { viewport: { width: 1366, height: 900 } });
  const page = await context.newPage();
  page.setDefaultTimeout(8000);  // fail fast so logged-and-skipped shots don't stall
  try {
    await fn(page);
  } catch (e) {
    failures.push(`[${roleKey}] fatal: ${e.message.split("\n")[0]}`);
    console.log(`  ‼ [${roleKey}] ${e.message.split("\n")[0]}`);
  }
  await context.close();
}

async function main() {
  const browser = await chromium.launch();

  // 0 — Login screen (no auth)
  if (!only) {
    await run(browser, "login", async (page) => {
      await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
      await page.getByRole("button", { name: /sign in/i }).waitFor();
      await settle(page);
      await shot(page, "login");
    });
  }

  // 1 — Site Engineer: lands on the site dashboard; filled site documents
  await run(browser, "eng", async (page) => {
    console.log("[eng]");
    await login(page, "eng");
    await step(page, "site-dashboard", async () => {});
    await step(page, "dpr-view-filled", () => openRef(page, "DPR-SJR-001"));
    await login(page, "eng");
    await step(page, "tws-form-blank", () => clickButton(page, "Prepare TWS"));
    await login(page, "eng");
    await step(page, "ir-view-filled", () => openRef(page, "IR-SJR-001"));
    await login(page, "eng");
    await step(page, "mar-view-filled", () => openRef(page, "MAR-SJR-001"));
    await login(page, "eng");
    await step(page, "dpr-form-blank", () => clickButton(page, "Prepare DPR"));
    await login(page, "eng");
    await step(page, "attendance", () => clickButton(page, "Attendance"));
  });

  // 2 — Site Admin / storekeeper: procurement + petty cash from the site
  await run(browser, "storekeeper", async (page) => {
    console.log("[storekeeper]");
    await login(page, "storekeeper");
    await step(page, "mr-view-filled", () => openRef(page, "MR-SJR-001"));
    await login(page, "storekeeper");
    await step(page, "pyr-view-filled", async () => {
      await clickText(page, "Payment register");   // paid PYR lives here
      await openRef(page, "PYR-SJR-001");
    });
    await login(page, "storekeeper");
    await step(page, "petty-cash", () => clickButton(page, "Petty Cash"));
    await login(page, "storekeeper");
    await step(page, "mr-form-blank", () => clickButton(page, "+ MR"));
  });

  // 3 — Project Manager: approvals queue + project workspace
  await run(browser, "pm", async (page) => {
    console.log("[pm]");
    await login(page, "pm");
    await step(page, "my-tasks-queue", async () => {});
    await step(page, "sites-list", () => group(page, "Sites"));
    await step(page, "pm-site-dashboard", () => openSite(page, "Soneva Jani"));
    await step(page, "project-workspace", () => clickButton(page, "Open project"));
  });

  // 4 — HO Purchasing: catalogue, suppliers, PR/LM
  await run(browser, "purchasing", async (page) => {
    console.log("[purchasing]");
    await login(page, "purchasing");
    await step(page, "purchasing-dashboard", () => group(page, "Procurement"));
    await step(page, "items-catalogue", () => subtab(page, "Items"));
    await step(page, "item-categories", () => subtab(page, "Item Categories"));
    await step(page, "suppliers", () => subtab(page, "Suppliers"));
    await login(page, "purchasing");
    await step(page, "pr-view-filled", async () => {
      await group(page, "Procurement");
      await tab(page, "PR Register");
      await openRef(page, "PR-001");
    });
    await login(page, "purchasing");
    await step(page, "lm-view-filled", async () => {
      await group(page, "Procurement");
      await tab(page, "LM Register");
      await openRef(page, "LM-001");
    });
  });

  // 5 — Director: My Tasks, Portfolio, Project Cost
  await run(browser, "director", async (page) => {
    console.log("[director]");
    await login(page, "director");
    await step(page, "director-my-tasks", async () => {});
    await step(page, "portfolio", () => subtab(page, "Portfolio"));
    await step(page, "project-cost", () => subtab(page, "Project Cost"));
  });

  // 6 — Signatory: the voucher authorisation queue
  await run(browser, "signatory", async (page) => {
    console.log("[signatory]");
    await login(page, "signatory");
    await step(page, "payment-vouchers-queue", async () => {});
    await step(page, "voucher-view", () => clickText(page, "PV-001"));
  });

  // 7 — Finance: dashboard, vouchers, cost
  await run(browser, "finance", async (page) => {
    console.log("[finance]");
    await login(page, "finance");
    await step(page, "finance-dashboard", async () => {});
    await step(page, "payment-vouchers", async () => {
      await group(page, "Finance");
      await subtab(page, "Payment Vouchers");
    });
    await step(page, "finance-project-cost", async () => {
      await group(page, "My Tasks");
      await subtab(page, "Project Cost");
    });
  });

  // 8 — HR & Payroll
  await run(browser, "hr", async (page) => {
    console.log("[hr]");
    await login(page, "hr");
    await step(page, "hr-dashboard", async () => {});
    await step(page, "employees", () => subtab(page, "Employees"));
    await step(page, "payroll", () => subtab(page, "Payroll"));
    await step(page, "staff-cost", () => subtab(page, "Staff Cost"));
  });

  // 9 — Admin: site setup, users, company
  await run(browser, "admin", async (page) => {
    console.log("[admin]");
    await login(page, "admin");
    await step(page, "admin-site-setup", () => group(page, "Admin"));
    await step(page, "admin-users", () => subtab(page, "Users"));
    await step(page, "admin-company", () => subtab(page, "Company"));
    await step(page, "admin-worker-categories", async () => {
      await group(page, "People");
      await subtab(page, "Worker Categories");
    });
  });

  // 10 — Mobile pass (the guide stresses phone use on site)
  await run(browser, "eng", async (page) => {
    console.log("[eng/mobile]");
    await login(page, "eng");
    await step(page, "mobile-site-dashboard", async () => {});
    await step(page, "mobile-dpr-view", () => openRef(page, "DPR-SJR-001"));
  }, { mobile: true });

  await browser.close();

  console.log(`\nCaptured ${seq} screenshots to ${OUT}`);
  if (failures.length) {
    console.log(`\n${failures.length} issue(s):`);
    failures.forEach((f) => console.log("  - " + f));
    process.exitCode = 1;
  }
}

main();
