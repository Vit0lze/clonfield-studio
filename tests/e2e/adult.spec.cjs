const { test } = require("@playwright/test");
const { open, settle, noErrorCard, expect } = require("./helpers.cjs");

// «Ocultar adulto» is ON by default, in every Library view, and one click turns it off.
test("Biblioteca: adulto oculto por padrão, interruptor sempre à vista e fácil de desligar", async ({ page }) => {
  const problems = await open(page, "#/library/lora");
  await settle(page); await noErrorCard(page);
  const toggle = page.getByRole("switch", { name: /Ocultar adulto/ });
  await expect(toggle).toBeVisible();
  await expect(toggle).toBeChecked();  // default ON, nothing stored yet
  await page.getByRole("button", { name: "Instalados" }).click();  // the switch is there in this view too, not only in Explorar
  await expect(page.getByRole("switch", { name: /Ocultar adulto/ })).toBeVisible();
  await expect(page.locator(".ccard", { hasText: "Film grain" })).toBeVisible();
  await expect(page.locator(".ccard", { hasText: "Night adult" })).toHaveCount(0);  // hidden by default
  await page.getByRole("switch", { name: /Ocultar adulto/ }).uncheck();
  await expect(page.locator(".ccard", { hasText: "Night adult" })).toBeVisible();   // one click shows it
  expect(await page.evaluate(() => localStorage.getItem("cf-hide-adult"))).toBe("0");
  await page.reload();
  await settle(page);
  await page.getByRole("button", { name: "Instalados" }).click();
  await expect(page.getByRole("switch", { name: /Ocultar adulto/ })).not.toBeChecked();  // the choice is remembered
  await expect(page.locator(".ccard", { hasText: "Night adult" })).toBeVisible();
  await page.getByRole("switch", { name: /Ocultar adulto/ }).check();
  await expect(page.locator(".ccard", { hasText: "Night adult" })).toHaveCount(0);
  expect(problems, problems.join("\n")).toEqual([]);
});

test("Pesquisar nos slots usa a mesma preferência (ligada por padrão) e a lembra", async ({ page }) => {
  await page.addInitScript(() => { try { sessionStorage.setItem("cf-prefill", JSON.stringify({ app: "create", values: { set: "Manual", model: "z-image", prompt: "x" } })); } catch {} });
  await open(page, "#/apps/create");
  await settle(page);
  await page.locator(".dock-chip", { hasText: "Modelo" }).click();
  const panel = page.locator('.dock-pop[aria-label="Modelo"]');
  await expect(panel).toBeVisible();
  // open any slot dropdown that offers «Pesquisar…» (Encoder / VAE / Upscaler)
  const triggers = panel.locator("button.dd-btn, button[aria-haspopup='listbox'], .dd > button");
  const n = await triggers.count();
  let opened = false;
  for (let i = 0; i < n && !opened; i++) {
    await triggers.nth(i).click();
    const footer = page.locator(".dd-footer:visible").first();
    if (await footer.count()) { await footer.click(); opened = true; } else { await triggers.nth(i).click(); }  // close it by clicking again: Escape would also close the Modelo popover
  }
  expect(opened, "nenhum slot ofereceu «Pesquisar…»").toBe(true);
  const modal = page.locator(".sr-overlay");
  await expect(modal).toBeVisible();
  const toggle = modal.getByRole("switch", { name: /Ocultar adulto/ });
  await expect(toggle).toBeChecked();
  await toggle.uncheck();
  expect(await page.evaluate(() => localStorage.getItem("cf-hide-adult"))).toBe("0");
});
