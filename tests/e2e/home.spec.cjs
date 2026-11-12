const { test } = require("@playwright/test");
const path = require("node:path");
const { open, settle, noErrorCard, expect } = require("./helpers.cjs");

const FIX = f => path.join(__dirname, "fixtures", f);

test("Início abre, anexa imagem e vídeo e leva a mídia ao app sugerido", async ({ page }) => {
  const problems = await open(page, "#/");
  await settle(page);
  await noErrorCard(page);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const attach = page.getByRole("button", { name: /Anexar imagem ou vídeo/ });
  await expect(attach).toBeVisible();
  await page.locator('input[type=file]').setInputFiles([FIX("portrait.png"), FIX("clip.mp4")]);
  await expect(page.locator(".home-thumb")).toHaveCount(2, { timeout: 15000 });
  await expect(page.locator(".home-thumb .bar")).toHaveCount(0, { timeout: 15000 });
  await page.locator(".quick textarea").fill("animar este retrato com movimento suave");
  const plan = page.waitForResponse(r => r.url().includes("/plan") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Sugerir" }).click();
  const response = await plan;
  expect(response.status()).toBe(200);
  const body = await response.json();
  expect(body.steps.length).toBeGreaterThan(0);
  const first = page.locator(".plan-step").first();
  await expect(first).toBeVisible();
  await first.click();
  await expect(page).toHaveURL(/#\/apps\//);
  await settle(page);
  await noErrorCard(page);
  // the attached photo arrived in the opened app, not just the URL
  await expect(page.locator(".thumbs .thumb img")).toHaveCount(1);
  expect(problems, problems.join("\n")).toEqual([]);
});
