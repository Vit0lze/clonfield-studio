const { test } = require("@playwright/test");
const path = require("node:path");
const { open, settle, noErrorCard, expect } = require("./helpers.cjs");

test("Folha de personagem: envia a imagem, escolhe as vistas e o pedido leva conjunto, modelo e quadro", async ({ page }) => {
  const problems = await open(page, "#/apps/character_sheet");
  await settle(page); await noErrorCard(page);
  await expect(page.getByText("Falta: Imagem do personagem").first()).toBeVisible();
  await page.locator("input[type=file]").first().setInputFiles(path.join(__dirname, "fixtures", "portrait.png"));
  await expect(page.getByText("Falta:")).toHaveCount(0, { timeout: 15000 });
  await page.getByRole("button", { name: "Vistas" }).click();
  await page.getByRole("option", { name: /Completo/ }).click({ force: true });
  const posted = [];
  await page.route("**/clonfield/api/jobs", route => { if (route.request().method() === "POST") { posted.push(route.request().postDataJSON()); return route.abort(); } return route.continue(); });
  const run = page.getByRole("button", { name: /Gerar|Executar|Aplicar|Criar/ }).last();
  await expect(run).toBeEnabled();
  await run.click();
  await expect.poll(() => posted.length).toBeGreaterThan(0);
  const params = posted[0].params || posted[0];
  expect(params).toMatchObject({ set: "full", model: "qwen21", size: "Vertical · 768 × 1152" });
  expect(problems.filter(p => !/net::ERR_FAILED/.test(p)), problems.join("\n")).toEqual([]);
});
