const { test } = require("@playwright/test");
const path = require("node:path");
const { open, settle, noErrorCard, expect } = require("./helpers.cjs");

test("Editar região: desenhar caixas sobre a imagem, remover, e o pedido leva as caixas em frações", async ({ page }) => {
  const problems = await open(page, "#/apps/region");
  await settle(page); await noErrorCard(page);
  await expect(page.getByText("Envie a imagem").first()).toBeVisible();
  await page.locator("input[type=file]").first().setInputFiles(path.join(__dirname, "fixtures", "portrait.png"));
  const layer = page.locator(".blayer");
  await expect(layer).toBeVisible({ timeout: 15000 });
  await layer.evaluate(el => el.scrollIntoView({ block: "center" }));  // keep the whole picture clear of the sticky footer
  await page.waitForTimeout(300);
  const box = await layer.boundingBox();
  // draw two boxes by dragging
  await page.mouse.move(box.x + box.width * 0.1, box.y + box.height * 0.2);
  await page.mouse.down(); await page.mouse.move(box.x + box.width * 0.4, box.y + box.height * 0.6, { steps: 6 }); await page.mouse.up();
  await page.mouse.move(box.x + box.width * 0.6, box.y + box.height * 0.5);
  await page.mouse.down(); await page.mouse.move(box.x + box.width * 0.9, box.y + box.height * 0.9, { steps: 6 }); await page.mouse.up();
  await expect(page.locator(".bbox")).toHaveCount(2);
  await expect(page.locator(".blist li")).toHaveCount(2);
  // a tiny accidental drag does not create a box
  await page.mouse.move(box.x + 5, box.y + 5); await page.mouse.down(); await page.mouse.move(box.x + 7, box.y + 6); await page.mouse.up();
  await expect(page.locator(".bbox")).toHaveCount(2);
  // remove the second with its × button, then draw it again so we send exactly two
  await page.getByRole("button", { name: "Remover caixa 2" }).click();
  await expect(page.locator(".bbox")).toHaveCount(1);
  await layer.evaluate(el => el.scrollIntoView({ block: "center" }));  // the click above scrolled the page: measure again
  await page.waitForTimeout(300);
  Object.assign(box, await layer.boundingBox());
  await page.mouse.move(box.x + box.width * 0.6, box.y + box.height * 0.5);
  await page.mouse.down(); await page.mouse.move(box.x + box.width * 0.9, box.y + box.height * 0.9, { steps: 6 }); await page.mouse.up();
  await expect(page.locator(".bbox")).toHaveCount(2);
  await page.locator("textarea").first().fill("trocar por um céu de pôr do sol");
  const posted = [];
  await page.route("**/clonfield/api/jobs", route => { if (route.request().method() === "POST") { posted.push(route.request().postDataJSON()); return route.abort(); } return route.continue(); });
  await page.getByRole("button", { name: /Gerar|Executar|Aplicar|Editar/ }).last().click();
  await expect.poll(() => posted.length).toBeGreaterThan(0);
  const params = posted[0].params || posted[0];
  expect(params.boxes).toHaveLength(2);
  const [a, b] = params.boxes;
  expect(Math.abs(a.x - 0.1)).toBeLessThan(0.03); expect(Math.abs(a.y - 0.2)).toBeLessThan(0.03);
  expect(Math.abs(a.w - 0.3)).toBeLessThan(0.04); expect(Math.abs(a.h - 0.4)).toBeLessThan(0.04);
  expect(b.x).toBeGreaterThan(0.55); expect(b.x + b.w).toBeLessThanOrEqual(1.0001);
  expect(problems.filter(p => !/net::ERR_FAILED/.test(p)), problems.join("\n")).toEqual([]);
});

test("sem caixa nem máscara, o app diz o que falta em vez de enviar", async ({ page }) => {
  await open(page, "#/apps/region");
  await settle(page);
  await page.locator("input[type=file]").first().setInputFiles(path.join(__dirname, "fixtures", "portrait.png"));
  await expect(page.locator(".blayer")).toBeVisible({ timeout: 15000 });
  await page.locator("textarea").first().fill("x");
  await expect(page.getByText(/uma caixa ou uma máscara/).first()).toBeVisible();
});
