// Playwright screenshot engine — ported from
// mcp-automation/src/verification/render_engine.py.
//
// Direct correspondences:
//   _disable_animations  → disableAnimations  (inject CSS to zero animation/transition)
//   wait_for_fonts=2000  → FONT_SETTLE_MS settle delay after networkidle
//   chromium args        → matches render_engine.py:84-91
//   default viewport     → DEFAULT_VIEWPORT (1440×900), but configurable per call
//   min size check       → MIN_SCREENSHOT_BYTES (<100KB → flagged + retry)
//
// New for VisualBot: full-page AND viewport screenshots are returned, because the
// PR comment is more readable with full-page but visual-diff scoring is more
// reliable with fixed-viewport (page height varies independently of UI changes).

import { chromium, type Browser, type Page } from "playwright";
import {
  DEFAULT_VIEWPORT,
  FONT_SETTLE_MS,
  MIN_SCREENSHOT_BYTES,
  type ScreenshotOutcome,
  type ViewportSize,
} from "./types.js";
import { log } from "./utils.js";

export interface ScreenshotOptions {
  pages: string[];
  viewport?: ViewportSize;
  pageTimeoutMs?: number; // hard timeout per page navigation+capture, default 30s
  maxRetries?: number; // default 2, on broken/too-small captures
  disableAnimations?: boolean; // default true
}

const DEFAULT_PAGE_TIMEOUT_MS = 30_000;
const DEFAULT_MAX_RETRIES = 2;

// Ported from render_engine.py:262-271 — _disable_animations.
// Produces stable screenshots regardless of in-flight CSS animations.
async function disableAnimations(page: Page): Promise<void> {
  await page.addStyleTag({
    content: `
      *, *::before, *::after {
        animation-duration: 0s !important;
        animation-delay: 0s !important;
        transition-duration: 0s !important;
        transition-delay: 0s !important;
        scroll-behavior: auto !important;
      }
    `,
  });
}

// Beyond networkidle: wait for document fonts and a short settle period for
// late-loading images / layout shifts. Matches render_engine.py's two-step
// "navigate → wait_for_fonts" pattern but with explicit document.fonts.ready.
async function waitForReady(page: Page, settleMs: number): Promise<void> {
  try {
    await page.evaluate(async () => {
      const d = document as Document & { fonts?: { ready: Promise<unknown> } };
      if (d.fonts?.ready) {
        await d.fonts.ready;
      }
    });
  } catch {
    // best-effort
  }
  await page.waitForTimeout(settleMs);
}

async function captureOnce(
  browser: Browser,
  port: number,
  pagePath: string,
  viewport: ViewportSize,
  pageTimeoutMs: number,
  shouldDisableAnimations: boolean
): Promise<{
  fullPage: Buffer;
  fullPageDimensions: ViewportSize;
  viewport: Buffer;
  viewportDimensions: ViewportSize;
  ms: number;
}> {
  const start = Date.now();
  const context = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();
  page.setDefaultNavigationTimeout(pageTimeoutMs);
  page.setDefaultTimeout(pageTimeoutMs);

  try {
    const url = `http://127.0.0.1:${port}${pagePath}`;
    log(`[shot] -> ${url} @ ${viewport.width}×${viewport.height}`);

    try {
      await page.goto(url, { waitUntil: "networkidle", timeout: pageTimeoutMs });
    } catch (err) {
      log(`[shot] networkidle timeout, falling back to load: ${(err as Error).message}`);
      await page.goto(url, {
        waitUntil: "load",
        timeout: Math.min(pageTimeoutMs, 20_000),
      });
    }

    if (shouldDisableAnimations) {
      await disableAnimations(page);
    }

    await waitForReady(page, FONT_SETTLE_MS);

    const fullPage = await page.screenshot({ fullPage: true, type: "png" });
    const viewportShot = await page.screenshot({ fullPage: false, type: "png" });

    // Read the resulting full-page height from the page itself — the viewport
    // height we configured isn't the same as the full-page screenshot height.
    const fullDims = await page.evaluate(() => ({
      width: document.documentElement.scrollWidth,
      height: document.documentElement.scrollHeight,
    }));

    return {
      fullPage,
      fullPageDimensions: { width: fullDims.width, height: fullDims.height },
      viewport: viewportShot,
      viewportDimensions: { width: viewport.width, height: viewport.height },
      ms: Date.now() - start,
    };
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
}

export async function screenshotPages(
  port: number,
  opts: ScreenshotOptions
): Promise<Map<string, ScreenshotOutcome>> {
  const viewport = opts.viewport ?? DEFAULT_VIEWPORT;
  const pageTimeoutMs = opts.pageTimeoutMs ?? DEFAULT_PAGE_TIMEOUT_MS;
  const maxRetries = opts.maxRetries ?? DEFAULT_MAX_RETRIES;
  const shouldDisableAnimations = opts.disableAnimations ?? true;

  const result = new Map<string, ScreenshotOutcome>();
  let browser: Browser | null = null;
  try {
    browser = await chromium.launch({
      headless: true,
      // render_engine.py:86-90 — security flags so file:// and cross-origin assets
      // load reliably even on the goofiest test repos.
      args: [
        "--disable-web-security",
        "--disable-features=IsolateOrigins,site-per-process",
        "--no-sandbox",
      ],
    });

    for (const path of opts.pages) {
      let lastErr: unknown;
      let captured:
        | Awaited<ReturnType<typeof captureOnce>>
        | null = null;
      let retryCount = 0;

      for (let attempt = 0; attempt <= maxRetries; attempt++) {
        try {
          const r = await captureOnce(
            browser,
            port,
            path,
            viewport,
            pageTimeoutMs,
            shouldDisableAnimations
          );
          // Min size check — too small means broken/blank/thumbnail.
          const fullSize = r.fullPage.byteLength;
          const vpSize = r.viewport.byteLength;
          if (
            fullSize < MIN_SCREENSHOT_BYTES &&
            vpSize < MIN_SCREENSHOT_BYTES &&
            attempt < maxRetries
          ) {
            log(
              `[shot] suspected broken capture (${fullSize}B / ${vpSize}B) on attempt ${attempt + 1}, retrying`
            );
            retryCount++;
            continue;
          }
          captured = r;
          retryCount = attempt;
          break;
        } catch (err) {
          lastErr = err;
          log(`[shot] attempt ${attempt + 1} for ${path} failed: ${(err as Error).message}`);
          if (attempt < maxRetries) {
            retryCount++;
            await new Promise((res) => setTimeout(res, 1000 * (attempt + 1)));
          }
        }
      }

      if (!captured) {
        const errMsg =
          lastErr instanceof Error
            ? lastErr.message
            : `Screenshot of ${path} failed after ${maxRetries + 1} attempts`;
        log(`[shot] ${path}: all attempts failed — ${errMsg}`);
        result.set(path, { ok: false, pagePath: path, error: errMsg });
        continue;
      }

      const fullSize = captured.fullPage.byteLength;
      const vpSize = captured.viewport.byteLength;
      const suspectedBroken =
        fullSize < MIN_SCREENSHOT_BYTES && vpSize < MIN_SCREENSHOT_BYTES;

      result.set(path, {
        ok: true,
        data: {
          pagePath: path,
          fullPage: captured.fullPage,
          fullPageBytes: fullSize,
          fullPageDimensions: captured.fullPageDimensions,
          viewport: captured.viewport,
          viewportBytes: vpSize,
          viewportDimensions: captured.viewportDimensions,
          suspectedBroken,
          captureMs: captured.ms,
          retryCount,
        },
      });
      log(
        `[shot] ${path}: full=${fullSize}B (${captured.fullPageDimensions.width}×${captured.fullPageDimensions.height}) ` +
          `vp=${vpSize}B (${captured.viewportDimensions.width}×${captured.viewportDimensions.height}) ` +
          `in ${captured.ms}ms${suspectedBroken ? " [SUSPECT]" : ""}`
      );
    }
  } finally {
    if (browser) await browser.close().catch(() => {});
  }
  return result;
}
