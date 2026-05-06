// Shared types for VisualBot.
// The screenshot/diff result shapes mirror what GodComet's Python pipeline
// returns from render_engine.py and visual_auditor.py — translated to the
// shapes that make sense for a PR-bot (no Figma metadata, no vision LLM yet).

export interface ViewportSize {
  width: number;
  height: number;
}

export interface ScreenshotResult {
  pagePath: string;
  // Full-page PNG — used in the PR comment (more useful for humans).
  fullPage: Buffer;
  fullPageBytes: number;
  fullPageDimensions: ViewportSize;
  // Viewport-only PNG at the configured viewport — used for visual diff.
  // GodComet's render_engine.py learned that fixed-viewport screenshots
  // produce more meaningful comparisons than full-page ones, because page
  // height varies independently of visual changes.
  viewport: Buffer;
  viewportBytes: number;
  viewportDimensions: ViewportSize;
  // True if either capture is suspiciously small (<100KB → likely thumbnail / blank).
  suspectedBroken: boolean;
  captureMs: number;
  retryCount: number;
}

export interface DiffResult {
  diffImage: Buffer;
  // pixelmatch-derived: fraction of pixels that differ, expressed 0-100.
  percentChanged: number;
  changedPixels: number;
  totalPixels: number;
  width: number;
  height: number;
  // Ported from visual_auditor.py: 1 - (changedPixels / totalPixels), clamped.
  pixelMatchScore: number;
  // Ported from visual_auditor.py: 1 - sum(|a - b|) / (size * 255).
  pixelSimilarityScore: number;
  // Ported from visual_auditor.py: SSIM on grayscale, 0-1.
  ssimScore: number;
  // structural * 0.5 + pixel * 0.5 (no vision LLM in MVP).
  compositeScore: number;
  // True if the input PNGs had different dimensions and we resized/padded.
  dimensionMismatch: boolean;
  // True if AR diff > 10% triggered the crop strategy.
  aspectRatioCropApplied: boolean;
  // True if either input was suspiciously small (<100KB).
  suspectedInvalidInput: boolean;
}

export interface PageDiff {
  pagePath: string;
  beforePng: Buffer;
  afterPng: Buffer;
  diff: DiffResult;
  viewport: ViewportSize;
}

export interface StageTiming {
  stage: string;
  ms: number;
}

export interface PipelineStageError extends Error {
  stage: string;
}

export const MIN_SCREENSHOT_BYTES = 100 * 1024; // 100KB — anything smaller is suspect.
export const PIXELMATCH_THRESHOLD = 0.1; // visual_auditor.py default.
export const VISUAL_CHANGE_THRESHOLD_PCT = 0.1; // PR threshold for posting a diff.
export const ASPECT_RATIO_MISMATCH_PCT = 0.10; // visual_auditor.py: >10% → crop.
export const DEFAULT_VIEWPORT: ViewportSize = { width: 1440, height: 900 };
export const FONT_SETTLE_MS = 2000; // render_engine.py wait_for_fonts.
