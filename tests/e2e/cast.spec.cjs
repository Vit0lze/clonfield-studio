const { test } = require("@playwright/test");
const path = require("node:path");
const { open, settle, noErrorCard, expect } = require("./helpers.cjs");

test("Elenco: cadastrar com imagem, chamar por @nome no pedido e remover", async ({ page }) => {
  page.on("dialog", d => d.accept());
  const problems = await open(page, "#/cast");
  await settle(page); await noErrorCard(page);
  await expect(page.getByText("O elenco está vazio")).toBeVisible();
  await page.getByLabel("Nome do personagem").fill("Marina");
  await page.getByLabel("Descrição do personagem").fill("mulher ruiva de jaqueta jeans");
  await page.locator('input[type=file][aria-label="Imagem do personagem"]').setInputFiles(path.join(__dirname, "fixtures", "portrait.png"));
  await expect(page.getByText(/Imagem: portrait\.png/)).toBeVisible({ timeout: 15000 });
  await page.getByRole("button", { name: "Adicionar ao elenco" }).click();
  const card = page.locator('.cast-card[data-name="Marina"]');
  await expect(card).toBeVisible();
  await expect(card.locator("img")).toHaveJSProperty("complete", true);
  expect(await card.locator("img").evaluate(img => img.naturalWidth)).toBeGreaterThan(10);  // the served picture really loads
  // a duplicate name comes back with the server's reason
  await page.getByLabel("Nome do personagem").fill("marina");
  await page.getByRole("button", { name: "Adicionar ao elenco" }).click();
  await expect(page.getByText(/Já existe um personagem chamado/)).toBeVisible();

  await open(page, "#/apps/create");
  await settle(page); await noErrorCard(page);
  const chip = page.locator(".cast-chips button", { hasText: "@Marina" });
  await expect(chip).toBeVisible();
  await page.locator("textarea").first().fill("passeando");
  await chip.click();
  await expect(page.locator("textarea").first()).toHaveValue(/passeando @Marina $/);
  const posted = [];
  await page.route("**/clonfield/api/jobs", route => { if (route.request().method() === "POST") { posted.push(route.request().postDataJSON()); return route.abort(); } return route.continue(); });
  await page.getByRole("button", { name: /Gerar|Executar|Aplicar|Criar/ }).last().click();
  await expect.poll(() => posted.length).toBeGreaterThan(0);
  expect((posted[0].params || posted[0]).prompt).toContain("@Marina");  // the server expands it, the page sends what you typed

  await open(page, "#/cast");
  await settle(page);
  await page.getByRole("button", { name: "Remover Marina" }).click();
  await expect(page.locator('.cast-card[data-name="Marina"]')).toHaveCount(0);
  await expect(page.getByText("O elenco está vazio")).toBeVisible();
  const unexpected = problems.filter(p => !/net::ERR_FAILED|status of 400/.test(p));  // the deliberate duplicate returns a 400
  expect(unexpected, unexpected.join("\n")).toEqual([]);
});
