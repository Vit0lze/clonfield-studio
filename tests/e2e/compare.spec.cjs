const { test } = require("@playwright/test");
const { open, settle, noErrorCard, expect } = require("./helpers.cjs");

test("Comparar modelos: três vagas de modelo, o pedido leva os modelos e o tempo quente", async ({ page }) => {
  const problems = await open(page, "#/apps/compare_models");
  await settle(page); await noErrorCard(page);
  await expect(page.getByRole("button", { name: "Modelo A" })).toContainText("Qwen Image 2.1");
  await expect(page.getByRole("button", { name: "Modelo B" })).toContainText("Turbo");
  await expect(page.getByRole("button", { name: "Modelo C (opcional)" })).toContainText("Nenhum");
  await page.locator("textarea").first().fill("um farol ao entardecer, pintura a óleo");
  const posted = [];
  await page.route("**/clonfield/api/jobs", route => { if (route.request().method() === "POST") { posted.push(route.request().postDataJSON()); return route.abort(); } return route.continue(); });
  const run = page.getByRole("button", { name: /Gerar|Executar|Aplicar|Comparar/ }).last();
  await expect(run).toBeEnabled();
  await run.click();
  await expect.poll(() => posted.length).toBeGreaterThan(0);
  const params = posted[0].params || posted[0];
  expect(posted[0].app || "compare_models").toBe("compare_models");
  expect(params).toMatchObject({ model_a: "qwen21", model_b: "qwen21-turbo", model_c: "none", warm: true, side: 768 });
  expect(problems.filter(p => !/net::ERR_FAILED/.test(p)), problems.join("\n")).toEqual([]);
});

test("Comparar modelos: escolher o mesmo modelo duas vezes volta o motivo do servidor, sem quebrar a tela", async ({ page }) => {
  await open(page, "#/apps/compare_models");
  await settle(page);
  await page.locator("textarea").first().fill("x");
  await page.getByRole("button", { name: "Modelo B" }).click();
  await page.getByRole("option", { name: /^Qwen Image 2\.1(?! Turbo)/ }).first().click({ force: true });
  const run = page.getByRole("button", { name: /Gerar|Executar|Aplicar|Comparar/ }).last();
  await run.click();
  await expect(page.getByText(/modelos diferentes|diferentes/i).first()).toBeVisible({ timeout: 20000 });
});
