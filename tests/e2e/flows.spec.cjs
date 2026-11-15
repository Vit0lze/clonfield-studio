const { test } = require("@playwright/test");
const path = require("node:path");
const fs = require("node:fs");
const { open, settle, noErrorCard, expect } = require("./helpers.cjs");

const PORTRAIT = path.join(__dirname, "fixtures", "portrait.png");

test("Fluxos: receitas listadas, passos mostrados, fila de duas execuções roda de verdade", async ({ page }) => {
  const problems = await open(page, "#/flows");
  await settle(page); await noErrorCard(page);
  await expect(page.locator(".flow-card")).toHaveCount(15);
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
  // redo from one step: a new job whose timeline shows the earlier steps coming from the cache
  const jobsBefore = await page.locator(".flow-job").count();
  await page.locator('.flow-job[data-job]').nth(1).locator('.flow-timeline li[data-step="sheet"] [data-action="redo"]').click();
  await expect(page.locator(".flow-job")).toHaveCount(jobsBefore + 1);
  const redone = page.locator(".flow-job").first();
  await expect(redone.locator('.flow-timeline li[data-step="sheet"]')).toHaveAttribute("data-state", "concluído", { timeout: 60000 });
  await expect(redone.locator('.flow-timeline li[data-step="look"]')).toHaveAttribute("data-state", "em cache");
  await expect(redone).toContainText("refeito");
  const first = page.locator(".flow-job").nth(1).locator("img");
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

test("Meus fluxos: um fluxo salvo aparece, roda com outro arquivo pela tela e pode ser apagado", async ({ page }) => {
  const problems = await open(page, "#/flows");
  await settle(page); await noErrorCard(page);
  await expect(page.locator(".flow-hint")).toContainText("Meus fluxos");
  // what the agent's save_flow does, through the same endpoint: upload one picture, save its graph with one exposed parameter
  const saved = await page.evaluate(async b64 => {
    const auth = { Authorization: "Bearer testpw-e2e" };
    const form = new FormData();
    form.append("files", new Blob([Uint8Array.from(atob(b64), c => c.charCodeAt(0))], { type: "image/png" }), "retrato.png");
    const [up] = await (await fetch("/clonfield/api/upload", { method: "POST", headers: auth, body: form })).json();
    const graph = { nodes: [{ id: "warm", label: "Dar o look", cap: "look", inputs: { image: { media: up.id } }, params: { look: "Cinema quente", strength: 60 } },
                            { id: "caption", label: "Escrever a legenda", cap: "caption", inputs: { image: { from: "warm.image" } }, params: { text: "plano um" } }] };
    const res = await fetch("/clonfield/api/recipes", { method: "POST", headers: { ...auth, "Content-Type": "application/json" },
      body: JSON.stringify({ graph, title: "Look com legenda", tagline: "Look e legenda", expose: [{ node: "warm", name: "look", label: "Look" }, { node: "caption", name: "text", label: "Legenda" }] }) });
    return { status: res.status, body: await res.json() };
  }, fs.readFileSync(PORTRAIT).toString("base64"));
  expect(saved.status).toBe(201);
  await page.reload(); await settle(page); await noErrorCard(page);
  await expect(page.locator(".flow-hint")).toHaveCount(0);
  const card = page.locator('.flow-card[data-recipe="meu_look_com_legenda"]');
  await expect(card).toContainText("seu fluxo");
  await card.click(); await settle(page); await noErrorCard(page);
  await page.locator('input[type=file][aria-label="Imagem"]').setInputFiles(PORTRAIT);
  await expect(page.locator(".flow-steps li[data-step]")).toHaveCount(2, { timeout: 15000 });
  await page.getByLabel("Legenda").fill("outro retrato");
  await page.getByLabel("Look", { exact: true }).selectOption({ label: "Preto e branco" });
  await page.getByRole("button", { name: "Rodar" }).click();
  await expect(page.locator('.flow-job[data-status="concluído"]')).toHaveCount(1, { timeout: 60000 });
  await expect(page.locator(".flow-job img")).toHaveCount(1);
  page.once("dialog", d => d.accept());
  await page.locator('[data-action="delete-flow"]').click();
  await expect(page).toHaveURL(/#\/flows$/);
  await settle(page);
  await expect(page.locator('.flow-card[data-recipe="meu_look_com_legenda"]')).toHaveCount(0);
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

test("Chat: o resultado do agente tem «Salvar como fluxo» e o fluxo aparece em Meus fluxos", async ({ page }) => {
  const problems = await open(page, `#/chat/${"b".repeat(32)}`);
  await settle(page); await noErrorCard(page);
  const keep = page.locator('[data-action="save-flow"]');
  await expect(keep).toBeVisible();
  page.once("dialog", d => d.accept("Pedidos do agente"));
  await keep.click();
  await expect(page.getByText("Fluxo guardado em Meus fluxos.")).toBeVisible();
  await open(page, "#/flows"); await settle(page); await noErrorCard(page);
  const card = page.locator('.flow-card[data-recipe="meu_pedidos_do_agente"]');
  await expect(card).toContainText("seu fluxo");
  await card.click(); await settle(page);
  await expect(page.locator(".flow-steps li[data-step]")).toHaveCount(2, { timeout: 15000 });
  page.once("dialog", d => d.accept());
  await page.locator('[data-action="delete-flow"]').click();
  await expect(page.locator('.flow-card[data-recipe="meu_pedidos_do_agente"]')).toHaveCount(0);
  expect(problems.filter(p => !/favicon/i.test(p))).toEqual([]);
});
