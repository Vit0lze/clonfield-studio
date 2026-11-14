const { test } = require("@playwright/test");
const { open, settle, noErrorCard, expect } = require("./helpers.cjs");

for (const app of ["create", "text2video"]) {
  test(`${app}: Gênero na frente, o resto da Direção em Avançado, e o pedido leva as escolhas`, async ({ page }) => {
    const problems = await open(page, `#/apps/${app}`);
    await settle(page); await noErrorCard(page);
    await page.locator("textarea").first().fill("um detetive caminha na chuva");
    if (app === "create") await page.locator(".dock-chip", { hasText: "Estilo" }).click();  // image apps keep the Estilo fields in the dock
    const genre = page.getByRole("button", { name: "Gênero" });
    await expect(genre).toContainText("Automático");
    await genre.click();
    await page.getByRole("option", { name: /Noir/ }).click({ force: true });
    await expect(genre).toContainText("Noir");
    const posted = [];
    await page.route("**/clonfield/api/jobs", route => { if (route.request().method() === "POST") { posted.push(route.request().postDataJSON()); return route.abort(); } return route.continue(); });
    const run = page.getByRole("button", { name: /Gerar|Executar|Aplicar|Criar/ }).last();
    await expect(run).toBeEnabled();
    await run.click();
    await expect.poll(() => posted.length).toBeGreaterThan(0);
    const params = posted[0].params || posted[0];
    expect(params.dir_genre).toBe("noir");
    expect(params.dir_light).toBe("auto");  // the server fills it from the genre, the form does not pretend to
    expect(problems.filter(p => !/net::ERR_FAILED/.test(p)), problems.join("\n")).toEqual([]);
  });
}
