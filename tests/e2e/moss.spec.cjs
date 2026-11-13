const { test } = require("@playwright/test");
const path = require("node:path");
const { open, settle, noErrorCard, expect } = require("./helpers.cjs");

test("MOSS: desenhar caixas, escolher texto/objeto, descrever, e o pedido leva tudo", async ({ page }) => {
  const problems = await open(page, "#/apps/moss");
  await settle(page); await noErrorCard(page);
  await page.locator("input[type=file]").first().setInputFiles(path.join(__dirname, "fixtures", "portrait.png"));
  const layer = page.locator(".blayer");
  await expect(layer).toBeVisible({ timeout: 15000 });
  await layer.evaluate(el => el.scrollIntoView({ block: "center" })); await page.waitForTimeout(300);
  let box = await layer.boundingBox();
  const draw = async (x0, y0, x1, y1) => { await layer.evaluate(el => el.scrollIntoView({ block: "center" })); await page.waitForTimeout(250); box = await layer.boundingBox(); await page.mouse.move(box.x + box.width * x0, box.y + box.height * y0); await page.mouse.down(); await page.mouse.move(box.x + box.width * x1, box.y + box.height * y1, { steps: 6 }); await page.mouse.up(); };
  await draw(0.1, 0.1, 0.6, 0.4);
  await expect(page.locator(".bform")).toBeVisible();
  await page.getByRole("button", { name: "Texto", exact: true }).click();
  await page.getByLabel("Texto da caixa 1").fill("OFERTA");
  await page.getByLabel("Descrição da caixa 1").fill("letras creme grandes no alto");
  await draw(0.2, 0.55, 0.8, 0.95);
  await page.getByLabel("Descrição da caixa 2").fill("um cavaleiro de armadura");
  await page.locator("textarea").last().fill("pôster de fantasia com um cavaleiro");
  const posted = [];
  await page.route("**/clonfield/api/jobs", route => { if (route.request().method() === "POST") { posted.push(route.request().postDataJSON()); return route.abort(); } return route.continue(); });
  const run = page.getByRole("button", { name: /Gerar|Executar|Aplicar|Editar/ }).last();
  await expect(run).toBeEnabled();
  await run.click();
  await expect.poll(() => posted.length).toBeGreaterThan(0);
  const params = posted[0].params || posted[0];
  expect(params.mode).toBe("generate");
  expect(params.boxes).toHaveLength(2);
  expect(params.boxes[0]).toMatchObject({ kind: "text", text: "OFERTA", desc: "letras creme grandes no alto" });
  expect(params.boxes[1]).toMatchObject({ kind: "obj", desc: "um cavaleiro de armadura" });
  expect(params.boxes[1].y).toBeGreaterThan(0.5);
  expect(problems.filter(p => !/net::ERR_FAILED/.test(p)), problems.join("\n")).toEqual([]);
});

test("MOSS: sem caixas o modo gerar avisa o que falta; editar por instrução não exige caixas", async ({ page }) => {
  await open(page, "#/apps/moss");
  await settle(page);
  await page.locator("textarea").last().fill("uma cena");
  await expect(page.getByText(/Falta:.*pelo menos uma caixa/).first()).toBeVisible();
  await page.locator(".dd-btn").first().click();  // «O que fazer» is a dropdown
  const option = page.locator(".dd-opt", { hasText: "Editar por instrução" }).first();
  await option.waitFor({ state: "attached" });
  await option.dispatchEvent("click");
  await expect(page.getByText(/pelo menos uma caixa/)).toHaveCount(0);
});

test("Imagem para 3D: formulário com motor, textura e tamanho dos pesos", async ({ page }) => {
  await open(page, "#/apps/image3d");
  await settle(page);
  await expect(page.getByText("Pixal3D").first()).toBeVisible();
  await expect(page.getByText("TRELLIS.2").first()).toBeVisible();
  await expect(page.getByText("Foto do objeto").first()).toBeVisible();
});
