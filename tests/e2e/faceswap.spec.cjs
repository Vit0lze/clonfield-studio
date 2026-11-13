const { test } = require("@playwright/test");
const path = require("node:path");
const { open, settle, noErrorCard, expect } = require("./helpers.cjs");

test("Trocar rosto: o pedido só segue com a confirmação de autorização e leva o consentimento", async ({ page }) => {
  const problems = await open(page, "#/apps/faceswap");
  await settle(page); await noErrorCard(page);
  const inputs = page.locator("input[type=file]");
  await inputs.nth(0).setInputFiles(path.join(__dirname, "fixtures", "portrait.png"));
  await inputs.nth(1).setInputFiles(path.join(__dirname, "fixtures", "portrait.png"));
  await expect(page.locator(".thumbs .thumb")).toHaveCount(2, { timeout: 15000 });
  await expect(page.getByText(/Tenho a autorização/).first()).toBeVisible();
  const run = page.getByRole("button", { name: /Gerar|Executar|Trocar/ }).last();
  const posted = [];
  await page.route("**/clonfield/api/jobs", route => { if (route.request().method() === "POST") { posted.push(route.request().postDataJSON()); return route.abort(); } return route.continue(); });
  await expect(run).toBeDisabled();  // the form itself blocks the request until the confirmation is given
  await expect(page.getByText(/Falta:.*Tenho a autorização/).first()).toBeVisible();
  expect(posted).toHaveLength(0);
  await page.getByRole("checkbox", { name: /Tenho a autorização/ }).check().catch(async () => { await page.locator("label.switch", { hasText: "Tenho a autorização" }).click(); });
  await expect(run).toBeEnabled();
  await run.click();
  await expect.poll(() => posted.length).toBeGreaterThan(0);
  expect((posted[0].params || posted[0]).consent).toBe(true);
  expect(problems.filter(p => !/net::ERR_FAILED/.test(p)), problems.join("\n")).toEqual([]);
});
