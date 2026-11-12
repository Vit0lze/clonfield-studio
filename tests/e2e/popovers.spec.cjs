const { test } = require("@playwright/test");
const { open, settle, noErrorCard, expect, SIZES } = require("./helpers.cjs");

// Each chip (Modelo / Formato / Estilo / Mais) must open a panel next to ITS OWN button, fully inside the viewport.
for (const size of SIZES) {
  test(`popovers ancorados ao próprio chip em ${size[0]}px`, async ({ page }) => {
    const problems = await open(page, "#/apps/create", size);
    await settle(page);
    await noErrorCard(page);
    const chips = page.locator(".dock-chip");
    const count = await chips.count();
    expect(count).toBeGreaterThanOrEqual(3);
    const lefts = [];
    for (let i = 0; i < count; i++) {
      const chip = chips.nth(i);
      const name = (await chip.locator(".chip-name").innerText()).trim();
      await chip.scrollIntoViewIfNeeded();
      await chip.click();
      const panel = page.locator(`.dock-pop[aria-label="${name}"]`);
      await expect(panel).toBeVisible();
      await page.waitForTimeout(300); // popIn animation
      const box = await panel.boundingBox();
      const cbox = await chip.boundingBox();
      const vw = size[0], vh = size[1];
      expect(box.x, `${name}: esquerda dentro da janela`).toBeGreaterThanOrEqual(-0.5);
      expect(box.x + box.width, `${name}: direita dentro da janela`).toBeLessThanOrEqual(vw + 0.5);
      expect(box.y, `${name}: topo dentro da janela`).toBeGreaterThanOrEqual(-0.5);
      expect(box.y + box.height, `${name}: base dentro da janela`).toBeLessThanOrEqual(vh + 0.5);
      if (size[0] > 600) {
        const gapV = Math.min(Math.abs(cbox.y - (box.y + box.height)), Math.abs(box.y - (cbox.y + cbox.height)));
        expect(gapV, `${name}: painel colado ao seu chip (gap vertical)`).toBeLessThanOrEqual(16);
        // the panel starts at its chip, not at a shared origin (unless clamped by the viewport edge)
        const expected = Math.min(Math.max(cbox.x, 8), vw - box.width - 8);
        expect(Math.abs(box.x - expected), `${name}: esquerda alinhada ao chip`).toBeLessThanOrEqual(2);
        lefts.push(Math.round(box.x));
      }
      // a11y + dismissal
      await expect(chip).toHaveAttribute("aria-expanded", "true");
      await page.keyboard.press("Escape");
      await expect(panel).toBeHidden();
      await expect(chip).toHaveAttribute("aria-expanded", "false");
    }
    if (size[0] > 600) expect(new Set(lefts).size, `painéis em origens distintas: ${lefts}`).toBeGreaterThan(1);
    // click outside closes
    await chips.first().click();
    await expect(page.locator(".dock-pop:visible")).toHaveCount(1);
    await page.mouse.click(size[0] / 2, 80);
    await expect(page.locator(".dock-pop:visible")).toHaveCount(0);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    expect(problems, problems.join("\n")).toEqual([]);
  });
}
