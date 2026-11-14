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

test("openjutsu (classe de 96 GB): também roda com offload, com aviso, nunca bloqueado", async ({ page }) => {
  await open(page, "#/apps/openjutsu");
  await settle(page);
  await expect(page.locator(".advice").filter({ hasText: "mais lento" })).toBeVisible();
  await expect(page.locator(".advice").filter({ hasText: "Precisa de uma placa" })).toHaveCount(0);
});

test("vídeo: o interruptor Rápido (LightX2V 4 passos) vai no pedido", async ({ page }) => {
  await open(page, "#/apps/text2video");
  await settle(page); await noErrorCard(page);
  await page.locator("textarea").first().fill("uma raposa corre na neve");
  await expect(page.getByText("Rápido: LoRA LightX2V de 4 passos").first()).toBeVisible();
  await page.getByLabel(/Rápido: LoRA LightX2V/).check();
  const posted = [];
  await page.route("**/clonfield/api/jobs", route => { if (route.request().method() === "POST") { posted.push(route.request().postDataJSON()); return route.abort(); } return route.continue(); });
  const run = page.getByRole("button", { name: /Gerar|Executar|Aplicar|Criar/ }).last();
  await expect(run).toBeEnabled();
  await run.click();
  await expect.poll(() => posted.length).toBeGreaterThan(0);
  expect((posted[0].params || posted[0]).fast).toBe(true);
});
