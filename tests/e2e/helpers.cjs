const { expect } = require("@playwright/test");

const PASSWORD = "testpw-e2e";
const SIZES = [[375, 812], [768, 1024], [1366, 768], [1920, 1080]];

// Opens the portal logged in and collects every page error / console error so a test can assert there are none.
async function open(page, hash = "#/", size = [1366, 768]) {
  const problems = [];
  page.on("pageerror", e => problems.push(`pageerror: ${e.message}`));
  page.on("console", m => { if (m.type() === "error") problems.push(`console.error: ${m.text()}`); });
  await page.setViewportSize({ width: size[0], height: size[1] });
  await page.addInitScript(pw => { try { sessionStorage.setItem("cf-token", pw); } catch {} }, PASSWORD);
  await page.goto(`/studio/${hash}`);
  return problems;
}

async function settle(page) { await page.waitForSelector("#root > *", { timeout: 15000 }).catch(() => {}); await page.waitForTimeout(1200); }

// The router catches view exceptions and renders an error card, so console checks alone miss them.
async function noErrorCard(page) { await expect(page.getByText("Não consegui abrir esta página")).toHaveCount(0); }

module.exports = { PASSWORD, SIZES, open, settle, noErrorCard, expect };
