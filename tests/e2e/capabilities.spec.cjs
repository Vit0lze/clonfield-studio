const { test } = require("@playwright/test");
const { open, settle, noErrorCard, expect } = require("./helpers.cjs");

test("Capacidades: catálogo tipado com estado de validação honesto e consumidores", async ({ page }) => {
  const problems = await open(page, "#/capabilities");
  await settle(page); await noErrorCard(page);
  const card = page.locator('[data-cap="upscale"]');
  await expect(card).toBeVisible();
  await expect(card.locator(".cap-port.t-image").first()).toContainText("image: image");
  await expect(card.locator(".cap-state .badge")).toContainText(/TESTADO CPU|CÓDIGO ESCRITO|BLOQUEADO_GPU/);
  await expect(card.locator(".cap-where li")).not.toHaveCount(0);
  // a GPU app must not claim a GPU test
  const gpu = page.locator('[data-cap="app.seethrough"] .cap-state .badge');
  await expect(gpu).toHaveText("BLOQUEADO_GPU");
  // filters
  const all = await page.locator(".cap-card").count();
  await page.getByRole("button", { name: "Compartilhadas" }).click();
  const shared = await page.locator(".cap-card").count();
  expect(shared).toBeGreaterThan(0); expect(shared).toBeLessThan(all);
  await page.getByRole("button", { name: "Todas" }).click();
  await page.getByLabel("Buscar capacidade").fill("quadro");
  await expect(page.locator('[data-cap="still"]')).toBeVisible();
  await expect(page.locator('[data-cap="upscale"]')).toHaveCount(0);
  expect(problems, problems.join("\n")).toEqual([]);
});

test("Criar mostra as capacidades que usa e leva ao catálogo com a capacidade em foco", async ({ page }) => {
  await open(page, "#/apps/create");
  await settle(page);
  const link = page.locator(".uses-bar a", { hasText: "Ampliar imagem" });
  await expect(link).toBeVisible();
  await link.click();
  await expect(page).toHaveURL(/#\/capabilities\/upscale/);
  await expect(page.locator('[data-cap="upscale"]')).toHaveClass(/focus/);
});

test("o chat mostra as chamadas de ferramenta reais do agente e o resultado", async ({ page }) => {
  const problems = await open(page, `#/chat/${"a".repeat(32)}`);
  await settle(page); await noErrorCard(page);
  const trace = page.locator(".agent-trace");
  await expect(trace.locator("summary")).toContainText("Passos do agente (3)");
  await trace.locator("summary").click();
  await expect(trace.locator("li")).toHaveCount(3);
  await expect(trace.locator("li").nth(0)).toContainText("Procurou capacidades");
  await expect(trace.locator("li.bad")).toContainText("Validou o grafo");  // the refused validation is shown as refused, not hidden
  await expect(trace.locator("li").nth(2)).toContainText("Executou o grafo");
  await expect(page.getByText("160×120 virou 320×240")).toBeVisible();
  expect(problems, problems.join("\n")).toEqual([]);
});
