const { test } = require("@playwright/test");
const path = require("node:path");
const { open, settle, noErrorCard, expect } = require("./helpers.cjs");

const PORTRAIT = path.join(__dirname, "fixtures", "portrait.png");

test("Fluxos: receitas listadas, passos mostrados, fila de duas execuções roda de verdade", async ({ page }) => {
  const problems = await open(page, "#/flows");
  await settle(page); await noErrorCard(page);
  await expect(page.locator(".flow-card")).toHaveCount(13);
  await expect(page.locator('.flow-card[data-recipe="loop_de_imagem"]')).toContainText("BLOQUEADO_GPU");
  await page.locator('.flow-card[data-recipe="polir_lote"]').click();
  await settle(page); await noErrorCard(page);
  // the steps are named before anything runs; with no pictures yet the preview says what is missing
  await expect(page.locator(".flow-steps .bad")).toContainText(/envie de 1 a 16/);
  await expect(page.getByRole("button", { name: "Rodar" })).toBeDisabled();

  await page.locator('input[type=file][aria-label="Imagens"]').setInputFiles([PORTRAIT, PORTRAIT]);
  await expect(page.locator(".flow-steps li[data-step]")).toHaveCount(4, { timeout: 15000 });
  await expect(page.locator('.flow-steps li[data-step="look"]')).toContainText("um por item");
  await expect(page.getByRole("button", { name: "Colocar na fila" })).toBeEnabled();

  await page.getByRole("button", { name: "Colocar na fila" }).click();
  await page.getByLabel("Look", { exact: true }).selectOption({ label: "Preto e branco" });
  await page.getByRole("button", { name: "Colocar na fila" }).click();
  await expect(page.locator(".flow-q")).toHaveCount(2);
  await page.getByRole("button", { name: "Rodar a fila (2)" }).click();
  await expect(page.locator(".flow-job")).toHaveCount(2);
  await expect(page.locator('.flow-job[data-status="concluído"]')).toHaveCount(2, { timeout: 90000 });
  // the per-step timeline comes from the run record: every step of the recipe, each with its own state
  const steps = page.locator(".flow-job").first().locator(".flow-timeline li[data-step]");
  await expect(steps).toHaveCount(4);
  await expect(page.locator(".flow-job").first().locator('.flow-timeline li[data-step="look"]')).toContainText("2 itens");
  await expect(page.locator(".flow-job").first().locator('.flow-timeline li[data-state="concluído"], .flow-timeline li[data-state="em cache"]')).toHaveCount(4);
  const first = page.locator(".flow-job").first().locator("img");
  await expect(first).toHaveCount(2);  // the sheet and the sharpest picture
  await expect(first.first()).toHaveJSProperty("complete", true);
  expect(await first.first().evaluate(img => img.naturalWidth)).toBeGreaterThan(50);
  expect(problems.filter(p => !/favicon/i.test(p))).toEqual([]);
});

test("Fluxos: apresentação de imagens vira um vídeo de verdade e as conferências são marcáveis", async ({ page }) => {
  const problems = await open(page, "#/flows/apresentacao_de_imagens");
  await settle(page); await noErrorCard(page);
  await page.locator('input[type=file][aria-label="Imagens"]').setInputFiles([PORTRAIT, PORTRAIT]);
  await expect(page.locator(".flow-steps li[data-step]")).toHaveCount(4, { timeout: 15000 });
  await page.getByLabel("Segundos por imagem").fill("1");
  await page.getByRole("button", { name: "Rodar" }).click();
  await expect(page.locator('.flow-job[data-status="concluído"]')).toHaveCount(1, { timeout: 90000 });
  const video = page.locator(".flow-job video");
  await expect(video).toHaveCount(1);
  await expect(page.locator('.flow-job .flow-timeline li[data-step="show"]')).toHaveAttribute("data-state", "concluído");
  await open(page, "#/flows/melhores_do_lote");
  await settle(page); await noErrorCard(page);
  const sharp = page.locator('input[data-option="sharp"]');
  await expect(sharp).toBeChecked();
  await sharp.uncheck();
  await page.locator('input[type=file][aria-label="Imagens"]').setInputFiles([PORTRAIT]);
  await expect(page.locator(".flow-steps li[data-step]")).toHaveCount(5, { timeout: 15000 });
  await page.locator('input[data-option="not_blank"]').uncheck();
  await expect(page.locator(".flow-steps .bad")).toContainText(/escolha entre/);
  expect(problems.filter(p => !/favicon/i.test(p))).toEqual([]);
});

test("Fluxos: formulário de GPU mostra o estado honesto e as linhas viram passos", async ({ page }) => {
  await open(page, "#/flows/storyboard_em_filme");
  await settle(page); await noErrorCard(page);
  await expect(page.locator(".flow-steps li[data-step]")).toHaveCount(5, { timeout: 15000 });
  await expect(page.locator(".flow-steps li[data-step=\"still\"]")).toContainText("um por item");
  await expect(page.locator("section .sr-chip", { hasText: "BLOQUEADO_GPU" })).toBeVisible();
  await page.locator("textarea").fill("só um plano");
  await expect(page.locator(".flow-steps .bad")).toContainText(/use de 2 a 6 linhas/);
});

test("Chat sem agente: pedido com vários estágios vira uma fila de 3 passos ligados", async ({ page }) => {
  await open(page, "#/chat");
  await settle(page); await noErrorCard(page);
  await page.getByLabel("Mensagem").fill("crie uma imagem de um farol em qualidade alta e depois faça um vídeo");
  await page.getByLabel("Mensagem").press("Enter");
  const rail = page.locator(".path .steps li.step");
  await expect(rail).toHaveCount(3, { timeout: 15000 });
  await expect(rail.nth(0)).toContainText("Criar");
  await expect(rail.nth(1)).toContainText(/Ampliar/);
  await expect(rail.nth(2)).toContainText("usa o resultado do passo anterior");
  await expect(rail.nth(1).getByRole("button", { name: "Executar" })).toBeEnabled();
});
