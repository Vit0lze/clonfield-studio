const { test } = require("@playwright/test");
const { open, settle, noErrorCard, expect } = require("./helpers.cjs");

// Estilo popover: ONE list of every LoRA the worker can see, classified for the model in use; the on/off switch is real.
async function openEstilo(page) {
  await page.locator(".dock-chip", { hasText: "Estilo" }).click();
  const panel = page.locator('.dock-pop[aria-label="Estilo"]');
  await expect(panel).toBeVisible();
  await expect(panel.locator(".lora-summary")).not.toContainText("Carregando");
  return panel;
}
const prefillModel = (page, model) => page.addInitScript(m => { try { sessionStorage.setItem("cf-prefill", JSON.stringify({ app: "create", values: { set: "Manual", model: m, prompt: "teste de lora" } })); } catch {} }, model);

test("LoRAs baixadas aparecem em Criar sem configuração e a lista explica o que é de outros modelos", async ({ page }) => {
  await prefillModel(page, "z-image");
  const problems = await open(page, "#/apps/create");
  await settle(page); await noErrorCard(page);
  const panel = await openEstilo(page);
  // compatible one is there without anyone adding it by hand
  await expect(panel.locator('.lora-row[data-name="film_grain__cv13.safetensors"]')).toBeVisible();
  await expect(panel.locator('.lora-row[data-name="film_grain__cv13.safetensors"] .ltag')).toHaveText("compatível");
  // the ones for other models are NOT in the default view, but the summary says how many exist
  await expect(panel.locator('.lora-row[data-name="pixel_style__cv11.safetensors"]')).toHaveCount(0);
  await expect(panel.locator(".lora-summary")).toContainText("1 instalada para Z-Image");
  await expect(panel.locator(".lora-summary")).toContainText("para outros modelos");
  // "Todas" shows them with reason, add disabled for the incompatible
  await panel.locator('[data-filter="all"]').click();
  const other = panel.locator('.lora-row[data-name="pixel_style__cv11.safetensors"]');
  await expect(other).toBeVisible();
  await expect(other.locator("button", { hasText: "Adicionar" })).toBeDisabled();
  await expect(other).toContainText("Qwen Image 2.1");
  // loose ComfyUI file, no hint
  await expect(panel.locator('.lora-row[data-name="mystery.safetensors"] .ltag')).toHaveText("sem informação");
  expect(problems, problems.join("\n")).toEqual([]);
});

test("com o modelo da LoRA, ela aparece como compatível; trocar de modelo muda a lista", async ({ page }) => {
  await prefillModel(page, "qwen21");
  await open(page, "#/apps/create");
  await settle(page);
  const panel = await openEstilo(page);
  await expect(panel.locator('.lora-row[data-name="pixel_style__cv11.safetensors"] .ltag')).toHaveText("compatível");
  await expect(panel.locator('.lora-row[data-name="film_grain__cv13.safetensors"]')).toHaveCount(0);
});

test("interruptor Ativar LoRA é visível, funciona e muda o que vai no pedido", async ({ page }) => {
  await prefillModel(page, "z-image");
  await open(page, "#/apps/create");
  await settle(page);
  const panel = await openEstilo(page);
  await panel.locator('.lora-row[data-name="film_grain__cv13.safetensors"] button', { hasText: "Adicionar" }).click();
  const card = panel.locator(".lora").first();
  const toggle = card.getByRole("switch");
  await expect(toggle).toBeVisible();
  await expect(toggle).toBeChecked();
  const posted = [];
  await page.route("**/clonfield/api/jobs", route => { if (route.request().method() === "POST") { posted.push(route.request().postDataJSON()); return route.abort(); } return route.continue(); });
  const submit = async () => { await page.keyboard.press("Escape"); await page.getByRole("button", { name: /Gerar/ }).click(); await expect.poll(() => posted.length).toBeGreaterThan(0); return posted.pop(); };
  let body = await submit();
  const params = b => b.params || b;
  expect(params(body).loras).toEqual([expect.objectContaining({ name: "film_grain__cv13.safetensors", on: true })]);
  // off
  await page.locator(".dock-chip", { hasText: "Estilo" }).click();
  await panel.locator(".lora").first().getByRole("switch").uncheck();
  await expect(panel.locator(".lora").first()).toHaveClass(/off/);
  await expect(page.locator(".dock-chip", { hasText: "Estilo" })).toContainText("nenhuma ativa");
  body = await submit();
  expect(params(body).loras).toEqual([expect.objectContaining({ name: "film_grain__cv13.safetensors", on: false })]);
});

test("LoRA que aparece depois (download no worker) entra na lista sem recarregar a página", async ({ page, request }) => {
  await prefillModel(page, "z-image");
  await open(page, "#/apps/create");
  await settle(page);
  const panel = await openEstilo(page);
  await expect(panel.locator(".lora-summary")).toContainText("1 instalada para Z-Image");
  // a LoRA lands in base/loras while the page is open (what a finished download does)
  const fs = require("node:fs"), path = require("node:path");
  const dir = path.join(process.env.CF_E2E_DATA, "loras");
  const src = path.join(dir, "film_grain__cv13.safetensors");
  fs.copyFileSync(src, path.join(dir, "second_zimage__cv14.safetensors"));
  fs.writeFileSync(path.join(dir, "second_zimage__cv14.json"), JSON.stringify({ title: "Second z", families: ["z-image"], model: 14, version: 14 }));
  // a real install job (it fails: the name is not in the library) goes through the real SSE follower, which emits the event
  await page.evaluate(async () => {
    const { api } = await import("/studio/js/api.js");
    const job = await api.post("/loras/install", { name: "nao_existe.safetensors" });
    api.follow(job.id, () => {});
  });
  await expect(panel.locator(".lora-summary")).toContainText("2 instaladas para Z-Image");
  await expect(panel.locator('.lora-row[data-name="second_zimage__cv14.safetensors"]')).toBeVisible();
});
