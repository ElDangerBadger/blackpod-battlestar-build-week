import { expect, test as base, type Locator, type Page } from "@playwright/test";

const oceanChunk = /\/assets\/NavigatorOceanView-[^/]+\.js(?:\?|$)/;
const overviewSelector = ".navigator-chart-overview";

const test = base.extend<{ browserAudit: void }>({
  browserAudit: [async ({ page, baseURL }, use) => {
    const errors: string[] = [];
    const origin = new URL(baseURL!).origin;
    page.on("pageerror", (error) => errors.push(error.message));
    // The test's own negative LIVE routes intentionally return 404. Other console
    // errors, including shader compilation failures, must still fail the test.
    page.on("console", (message) => {
      if (message.type() === "error" && !message.text().includes("Failed to load resource:")) {
        errors.push(message.text());
      }
    });
    await page.route("**/*", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.origin !== origin || !["GET", "HEAD"].includes(request.method())) {
        errors.push(`Unexpected external or mutating request: ${request.method()} ${url.origin}${url.pathname}`);
        await route.abort();
        return;
      }
      await route.continue();
    });
    await use();
    expect(errors, "The presentation should have no runtime errors or external/mutating requests").toEqual([]);
  }, { auto: true }],
});

async function openDemo(page: Page) {
  await page.goto("?mode=demo");
  const overview = page.locator(overviewSelector);
  await expect(overview).toBeVisible();
  await expect(page.getByRole("complementary", { name: "Presentation data mode" })).toContainText("DEMO");
  return overview;
}

async function openNavigator(page: Page) {
  await (await openDemo(page)).click();
  const dialog = page.getByRole("dialog", { name: "Navigator Ship View" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("SHADOW presentation only · no trade or order execution");
  return dialog;
}

async function waitForOcean(dialog: Locator) {
  const canvas = dialog.locator("canvas");
  await expect(canvas).toBeVisible();
  await expect(dialog.locator(".navigator-ocean")).toHaveAttribute("data-reduced-motion", "true");
  // Canvas mounts before R3F configures Three. CameraRig sets this cursor only
  // after initialization and the preceding context-loss monitor have committed.
  // In particular, do not create a context ourselves on an uninitialized canvas.
  await expect(canvas).toHaveCSS("cursor", "grab", { timeout: 45_000 });
  return canvas;
}

async function assertInertBackground(page: Page, dialog: Locator) {
  const background = page.locator(".cabin-scene > .cabin-content");
  await expect(background).toHaveAttribute("inert", "");
  await expect(background).toHaveAttribute("aria-hidden", "true");
  for (const selector of [overviewSelector, ".presentation-mode-control button", ".replay-theater button"]) {
    const blocked = await page.locator(selector).first().evaluate((element: HTMLElement) => {
      element.focus();
      return document.activeElement !== element;
    });
    expect(blocked, `${selector} must reject programmatic focus while a dialog is open`).toBe(true);
  }
  await expect(dialog.getByRole("button", { name: /^Return to (bridge|full cabin)$/ })).toBeFocused();
}

test("transparent ledger overview loads the actual production PNG @asset-layout", async ({ page }, testInfo) => {
  const imageResponse = page.waitForResponse((response) => new URL(response.url()).pathname.endsWith("/captains-cabin-template.png"));
  const overview = await openDemo(page);
  const response = await imageResponse;
  expect(response.ok()).toBe(true);
  expect(response.headers()["content-type"]).toMatch(/^image\/png/);
  expect((await response.body()).subarray(0, 8).toString("hex")).toBe("89504e470d0a1a0a");
  const scene = page.locator(".cabin-scene");
  const background = await scene.evaluate(async (element) => {
    const url = getComputedStyle(element).backgroundImage.match(/^url\(["']?(.*?)["']?\)$/)?.[1];
    if (!url) throw new Error("Cabin background image has no URL");
    const image = new Image();
    image.src = url;
    await image.decode();
    return { url, width: image.naturalWidth, height: image.naturalHeight };
  });
  expect(background.width).toBeGreaterThan(1000);
  expect(background.height).toBeGreaterThan(700);
  expect(background.url).toBe(new URL("captains-cabin-template.png", testInfo.project.use.baseURL).href);
  await expect(overview.locator("svg")).toBeVisible();
  await expect(overview.locator(".navigator-ship__plot-wrap")).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
  await expect(overview.locator(".navigator-ship__plot-wrap")).toHaveCSS("box-shadow", "none");
  await expect(overview.locator(".navigator-ship__sea")).toHaveCount(0);
  await expect(overview.locator(".navigator-ship__wake")).toHaveAttribute("d", /^M.+L/);
  await testInfo.attach("ledger-overview", { body: await scene.screenshot(), contentType: "image/png" });
});

test("expansion lazily loads V3, renders canvas, changes camera and restores focus", async ({ page }, testInfo) => {
  const scripts: string[] = [];
  page.on("request", (request) => { if (request.resourceType() === "script") scripts.push(request.url()); });
  const overview = await openDemo(page);
  expect(scripts.filter((url) => oceanChunk.test(url))).toEqual([]);
  await expect(page.locator("canvas")).toHaveCount(0);
  const loadedOcean = page.waitForResponse((response) => oceanChunk.test(response.url()) && response.ok());
  await overview.click();
  await loadedOcean;
  const dialog = page.getByRole("dialog", { name: "Navigator Ship View" });
  const canvas = await waitForOcean(dialog);
  await expect(dialog.locator(".navigator-ocean-fallback")).toHaveCount(0);
  await assertInertBackground(page, dialog);
  const facts = await dialog.getByRole("definition").allTextContents();
  expect(facts.length, "Expanded Navigator must expose its supplied market facts").toBeGreaterThan(0);
  await dialog.getByRole("button", { name: "Chart view", exact: true }).click();
  await expect(dialog.getByRole("slider", { name: "Camera vantage" })).toHaveValue("1");
  const chart = await canvas.screenshot();
  await dialog.getByRole("button", { name: "Ship view", exact: true }).click();
  await expect(dialog.getByRole("slider", { name: "Camera vantage" })).toHaveValue("0");
  const ship = await canvas.screenshot();
  expect(ship.equals(chart), "The rendered camera endpoints should be visibly different").toBe(false);
  expect(await dialog.getByRole("definition").allTextContents()).toEqual(facts);
  await expect(dialog).toContainText("SHADOW presentation only · no trade or order execution");
  await testInfo.attach("expanded-ship", { body: ship, contentType: "image/png" });
  await testInfo.attach("expanded-chart", { body: chart, contentType: "image/png" });
  const firstControl = dialog.getByRole("button", { name: "Return to bridge" });
  await firstControl.focus();
  await page.keyboard.press("Shift+Tab");
  await expect(firstControl).not.toBeFocused();
  expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Tab");
  await expect(firstControl).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(overview).toBeFocused();
  await expect(page.locator(".cabin-content")).not.toHaveAttribute("inert", "");
});

for (const title of ["Oracle", "Configuration"]) {
  test(`${title} modal blocks background controls and returns to its trigger`, async ({ page }) => {
    await openDemo(page);
    const trigger = title === "Oracle"
      ? page.getByRole("button", { name: "Open Oracle book", exact: true })
      : page.getByRole("button", { name: "Config Not included", exact: true });
    await trigger.click();
    const dialog = page.getByRole("dialog", { name: title, exact: true });
    await expect(dialog).toBeVisible();
    await assertInertBackground(page, dialog);
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(trigger).toBeFocused();
  });
}

test("replay steps remain deterministic and preserve the SHADOW outcome", async ({ page }) => {
  await openDemo(page);
  const safety = page.locator(".paper-order-copy");
  await expect(safety).toContainText("NO ORDER CREATED");
  await page.getByRole("button", { name: "Restart", exact: true }).click();
  await expect(page.locator("main[data-replay-stage]")).toHaveAttribute("data-replay-stage", "RESET");
  await expect(safety).toContainText("NO ORDER EXECUTION");
  const expectedStages = ["HARBORMASTER", "ORACLE", "MODELDOCK", "COUNCIL", "GOVERNOR", "OPERATOR", "NAVIGATOR", "MISSION"];
  for (const stage of expectedStages) {
    await page.getByRole("button", { name: "Step", exact: true }).click();
    await expect(page.locator("main[data-replay-stage]")).toHaveAttribute("data-replay-stage", stage);
  }
  await expect(page.getByRole("button", { name: "Step", exact: true })).toBeDisabled();
  await expect(safety).toContainText("NO ORDER CREATED");
  await expect(safety).toContainText("SHADOW");
  await expect(safety).toContainText("APPROVED");
});

for (const failure of ["missing", "invalid"] as const) {
  test(`LIVE pack ${failure} fails honestly without loading DEMO`, async ({ page }) => {
    const requested: string[] = [];
    page.on("request", (request) => requested.push(request.url()));
    await page.route("**/demo/live/**", (route) => route.fulfill(failure === "missing"
      ? { status: 404, contentType: "text/plain", body: "No LIVE pack prepared" }
      : { status: 200, contentType: "application/json", body: "{ invalid canonical artifact" }));
    await page.goto("?mode=live");
    await expect(page.getByRole("heading", { name: "Mission evidence could not be validated." })).toBeVisible();
    await expect(page.getByText(/^LIVE mission pack:/)).toBeVisible();
    await expect(page.getByText(/No alternate mode was substituted\./)).toBeVisible();
    await expect(page.getByRole("button", { name: "Live", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator(overviewSelector)).toHaveCount(0);
    expect(requested.some((url) => url.includes("/demo/live/"))).toBe(true);
    expect(requested.some((url) => url.includes("/demo/approved/"))).toBe(false);
  });
}

test("missing WebGL preserves the supplied SVG and never requests the 3D bundle", async ({ page }) => {
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, type: string, ...args: unknown[]) {
      if (["webgl", "webgl2", "experimental-webgl"].includes(type)) return null;
      return Reflect.apply(original, this, [type, ...args]);
    } as typeof original;
  });
  const requested: string[] = [];
  page.on("request", (request) => requested.push(request.url()));
  const dialog = await openNavigator(page);
  await expect(dialog.getByText("3D ocean unavailable; canonical chart shown.", { exact: true })).toBeVisible();
  await expect(dialog.locator(".navigator-ship--interactive svg")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Zoom in", exact: true })).toBeVisible();
  await expect(dialog).toContainText("DEMO · REPLAY");
  expect(requested.some((url) => oceanChunk.test(url))).toBe(false);
});

test("WebGL context loss returns to the same supplied SVG and SHADOW boundary", async ({ page }) => {
  const dialog = await openNavigator(page);
  const canvas = await waitForOcean(dialog);
  const didLose = await canvas.evaluate((element: HTMLCanvasElement) => {
    const gl = element.getContext("webgl2");
    const extension = gl?.getExtension("WEBGL_lose_context");
    if (!extension) return false;
    extension.loseContext();
    return true;
  });
  expect(didLose, "Software WebGL should expose real context-loss testing").toBe(true);
  await expect(dialog.getByText("3D ocean unavailable; canonical chart shown.", { exact: true })).toBeVisible();
  await expect(dialog.locator(".navigator-ship--interactive svg")).toBeVisible();
  await expect(dialog.locator(".navigator-ship--interactive .navigator-ship__wake")).toHaveAttribute("d", /^M.+L/);
  await expect(dialog).toContainText("SHADOW presentation only · no trade or order execution");
  await expect(dialog).toContainText("DEMO · REPLAY");
});
