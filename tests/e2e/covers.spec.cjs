const { test } = require("@playwright/test");
const { open, settle, noErrorCard, expect } = require("./helpers.cjs");

// Images must not remount or be refetched when a list repaints (polling every 4 s, favourites toggling, job events).

test("Criar: miniaturas recentes não remontam nem rebaixam em 10 ciclos de atualização + 2 reais", async ({ page }) => {
  const filesRequests = [];
  page.on("request", r => { if (r.url().includes("/clonfield/api/files/")) filesRequests.push(r.url()); });
  const problems = await open(page, "#/apps/create");
  await settle(page); await noErrorCard(page);
  await expect(page.locator(".recents .recent img")).toHaveCount(3);
  await page.waitForFunction(() => [...document.querySelectorAll(".recents img")].every(i => i.complete && i.naturalWidth > 0));
  const mutations = await page.evaluate(() => { window.__mut = []; const target = document.querySelector(".recents");
    window.__obs = new MutationObserver(list => list.forEach(m => m.addedNodes.forEach(n => window.__mut.push("+" + (n.nodeName || ""))) || list.forEach(m => m.removedNodes.forEach(n => window.__mut.push("-" + (n.nodeName || ""))))));
    window.__obs.observe(target, { childList: true, subtree: true });
    document.querySelectorAll(".recents img").forEach(i => { i.__mark = 1; }); return 0; });
  const baseline = filesRequests.length;
  // 10 forced repaints through the same event the poller emits, then 2 real poll cycles (4 s each)
  await page.evaluate(async () => { const { events } = await import("/studio/js/api.js"); for (let i = 0; i < 10; i++) { events.dispatchEvent(new Event("jobs")); await new Promise(r => setTimeout(r, 30)); } });
  await page.waitForTimeout(8500);
  const result = await page.evaluate(() => ({ mut: window.__mut, kept: [...document.querySelectorAll(".recents img")].filter(i => i.__mark === 1).length, total: document.querySelectorAll(".recents img").length }));
  expect(result.mut, `nós recriados: ${result.mut}`).toEqual([]);
  expect(result.kept).toBe(3);
  expect(filesRequests.length - baseline, "novas requisições de imagem depois da pintura inicial").toBe(0);
  expect(problems, problems.join("\n")).toEqual([]);
});

test("a URL assinada de uma imagem é a mesma entre duas leituras da fila", async ({ page }) => {
  await open(page, "#/");
  await settle(page);
  const urls = await page.evaluate(async () => {
    const get = async () => (await (await fetch("/clonfield/api/jobs?limit=5", { headers: { Authorization: "Bearer testpw-e2e" } })).json()).flatMap(j => j.results.map(r => r.url));
    const a = await get(); await new Promise(r => setTimeout(r, 1300)); const b = await get(); return { a, b };
  });
  expect(urls.a.length).toBeGreaterThan(0);
  expect(urls.b).toEqual(urls.a);
});

test("Biblioteca: favoritar uma carta reordena sem recriar as capas das outras", async ({ page }) => {
  const problems = await open(page, "#/library");
  await settle(page); await noErrorCard(page);
  const cards = page.locator(".ccard:not(.skeleton)");
  await expect(cards.first()).toBeVisible();
  const before = await cards.count();
  expect(before).toBeGreaterThan(2);
  await page.waitForFunction(() => [...document.querySelectorAll(".ccard img")].every(i => i.complete));
  await page.evaluate(() => document.querySelectorAll(".ccard").forEach(c => { c.__mark = 1; }));
  await cards.nth(1).locator("button.fav-star").click();
  await page.waitForTimeout(800);
  const kept = await page.evaluate(() => [...document.querySelectorAll(".ccard")].filter(c => c.__mark === 1).length);
  expect(kept, "cartas preservadas depois do favorito").toBe(before);
  expect(problems, problems.join("\n")).toEqual([]);
});

test("a capa autoral do modelo não é substituída pela última geração guardada no navegador", async ({ page }) => {
  await page.addInitScript(() => { try { localStorage.setItem("cf-cover-qwen21", "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="); } catch {} });
  const problems = await open(page, "#/library");
  await settle(page); await noErrorCard(page);
  expect(await page.evaluate(() => localStorage.getItem("cf-cover-qwen21")), "resíduo cf-cover-* removido").toBeNull();
  const sources = await page.locator(".ccard img").evaluateAll(list => list.map(i => i.getAttribute("src")));
  expect(sources.some(s => /model-qwen21/.test(s)), `capas: ${sources}`).toBe(true);
  expect(sources.some(s => s.startsWith("data:")), "nenhuma capa vinda de localStorage").toBe(false);
  expect(problems, problems.join("\n")).toEqual([]);
});
