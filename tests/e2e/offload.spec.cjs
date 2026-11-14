const { test } = require("@playwright/test");
const { open, settle, noErrorCard, expect } = require("./helpers.cjs");

// The card in the e2e engine is 15 GB. Apps that want 24 GB stream weights to RAM/disk (slow, not refused); the 96 GB class stays refused.
for (const id of ["scail2", "animate2"]) {
  test(`${id}: placa de 15 GB recebe aviso de lentidão, não bloqueio`, async ({ page }) => {
    const problems = await open(page, `#/apps/${id}`);
    await settle(page); await noErrorCard(page);
    await expect(page.locator(".advice").filter({ hasText: "mais lento" })).toBeVisible();
    await expect(page.locator(".advice").filter({ hasText: "Precisa de uma placa" })).toHaveCount(0);
    expect(problems, problems.join("\n")).toEqual([]);
  });
}

test("openjutsu: sem caminho de offload, continua bloqueado com o motivo", async ({ page }) => {
  await open(page, "#/apps/openjutsu");
  await settle(page);
  await expect(page.locator(".advice").filter({ hasText: "Precisa de uma placa com ~90 GB" })).toBeVisible();
});
