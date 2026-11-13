const { test } = require("@playwright/test");
const { open, settle, noErrorCard, expect, SIZES } = require("./helpers.cjs");

const ROUTES = ["#/", "#/chat", "#/apps", "#/apps/create", "#/apps/edit", "#/apps/upscale", "#/apps/text2video", "#/apps/animate", "#/apps/outpaint", "#/apps/moss", "#/apps/image3d", "#/apps/audio", "#/apps/faceswap", "#/apps/factory", "#/apps/restore", "#/apps/outfit", "#/library", "#/history", "#/jobs", "#/system", "#/capabilities"];

for (const size of SIZES) {
  for (const route of ROUTES) {
    test(`rota ${route} sem erros em ${size[0]}px`, async ({ page }) => {
      const problems = await open(page, route, size);
      await settle(page);
      await expect(page.locator("#root")).not.toBeEmpty();
      await noErrorCard(page);
      expect(problems, problems.join("\n")).toEqual([]);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, "overflow horizontal").toBeLessThanOrEqual(1);
    });
  }
}
