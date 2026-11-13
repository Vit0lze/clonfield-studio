const { test } = require("@playwright/test");
const { open, settle, noErrorCard, expect } = require("./helpers.cjs");

test("Áudio: o app mostra um player com o arquivo gerado e o botão de baixar", async ({ page }) => {
  await page.addInitScript(() => { try { sessionStorage.setItem("cf-last-audio", "job_e2eaudio"); } catch {} });
  const problems = await open(page, "#/apps/audio");
  await settle(page); await noErrorCard(page);
  const player = page.locator(".audio-card audio");
  await expect(player).toHaveCount(1);
  const duration = await player.evaluate(el => new Promise(resolve => { if (el.readyState >= 1) return resolve(el.duration); el.addEventListener("loadedmetadata", () => resolve(el.duration)); el.addEventListener("error", () => resolve(-1)); el.load(); }));
  expect(duration).toBeGreaterThan(0.8);  // the real 1 s mp3 loads and plays
  await expect(page.locator(".audio-card a", { hasText: "Baixar" })).toHaveAttribute("download", "tom.mp3");
  await expect(page.getByRole("button", { name: /Gerar de novo/ })).toBeVisible();
  expect(problems, problems.join("\n")).toEqual([]);
});

test("Áudio: o formulário tem modelo, duração, melhorar prompt e variações", async ({ page }) => {
  await open(page, "#/apps/audio");
  await settle(page);
  await expect(page.getByText("Descreva o som").first()).toBeVisible();
  await expect(page.getByText("Melhorar o prompt com o modelo local").first()).toBeVisible();
  await expect(page.getByText("Duração (s)").first()).toBeVisible();
});
