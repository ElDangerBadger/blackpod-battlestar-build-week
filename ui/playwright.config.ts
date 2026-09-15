import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { defineConfig } from "@playwright/test";

// Use the real prepared capture; never manufacture market observations or LIVE provenance.
const demoRoot = new URL("./public/demo/approved/", import.meta.url);
for (const artifact of [
  "mission_snapshot.json",
  "presentation/mission_summary.json",
  "presentation/captains_log.json",
  "presentation/demo_manifest.json",
  "presentation/cabin_context.json",
  "presentation/navigator_market.json",
]) {
  if (!existsSync(new URL(artifact, demoRoot))) {
    throw new Error(
      `Browser tests need the prepared DEMO pack with its captured Navigator market artifact. Missing: ${artifact}. `
      + "Run make cabin-prepare BATTLESTAR_PATH=/path/to/read-only/battlestar; CABIN_DEMO_MARKET_FIXTURE selects the documented captured series.",
    );
  }
}
const manifest = JSON.parse(readFileSync(new URL("presentation/demo_manifest.json", demoRoot), "utf8"));
if (manifest.run_mode !== "REPLAY" || manifest.shadow_only_declaration !== "NAVIGATOR_SHADOW_ONLY_NO_EXECUTION") {
  throw new Error("Browser tests require a REPLAY/SHADOW DEMO pack; the supplied pack does not meet that boundary.");
}

const origin = "http://127.0.0.1:4317";
const mountedOrigin = "http://127.0.0.1:4318";

export default defineConfig({
  testDir: "./e2e",
  outputDir: "../output/playwright/regressions/results",
  reporter: [
    ["list"],
    ["html", { outputFolder: "../output/playwright/regressions/report", open: "never" }],
  ],
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  use: {
    browserName: "chromium",
    // Set PLAYWRIGHT_CHANNEL=chrome to use installed Chrome instead of Playwright Chromium.
    channel: process.env.PLAYWRIGHT_CHANNEL || undefined,
    viewport: { width: 1280, height: 960 },
    contextOptions: { reducedMotion: "reduce" },
    launchOptions: {
      args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
    },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    serviceWorkers: "block",
  },
  projects: [
    { name: "production", use: { baseURL: `${origin}/` } },
    {
      name: "production-subpath",
      use: { baseURL: `${mountedOrigin}/cabin/` },
      grep: /@asset-layout/,
    },
  ],
  // Both preview instances serve the same relative-base production bundle.
  // Strict ports and no reuse prevent a stale development server from passing tests.
  webServer: [
    {
      command: "npm run preview -- --host 127.0.0.1 --port 4317 --strictPort",
      cwd: fileURLToPath(new URL(".", import.meta.url)),
      url: `${origin}/`,
      reuseExistingServer: false,
    },
    {
      command: "npm run preview -- --host 127.0.0.1 --port 4318 --strictPort --base /cabin/",
      cwd: fileURLToPath(new URL(".", import.meta.url)),
      url: `${mountedOrigin}/cabin/`,
      reuseExistingServer: false,
    },
  ],
});
