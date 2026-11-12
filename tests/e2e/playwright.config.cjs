const { defineConfig } = require("@playwright/test");
const path = require("node:path");
const os = require("node:os");

// Real engine (cf_engine.py), real portal, no stubs. FAKE_VRAM only unlocks apps in the UI on a machine without a GPU;
// it never counts as GPU evidence. Playwright's runner hangs loading ESM specs here, so specs are CommonJS.
const root = path.resolve(__dirname, "../..");
const data = process.env.CF_E2E_DATA || path.join(os.tmpdir(), "cf-e2e-data");
const port = process.env.CF_E2E_PORT || "7871";
module.exports = defineConfig({
  testDir: ".",
  testMatch: /.*\.spec\.cjs/,
  timeout: 60000,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: { baseURL: `http://127.0.0.1:${port}`, headless: true },
  webServer: {
    command: `${process.env.CF_PY || "python3"} cf_engine.py --port ${port}`,
    cwd: root,
    url: `http://127.0.0.1:${port}/studio/`,
    reuseExistingServer: Boolean(process.env.CF_E2E_REUSE),
    timeout: 60000,
    env: { ...process.env, CLONFIELD_FAKE_VRAM: "15", CLONFIELD_PASSWORD: "testpw-e2e", CLONFIELD_DIR: data, CLONFIELD_COMFY_MODELS: path.join(data, "comfy-models") }
  }
});
