// Visual diff engine — ported from mcp-automation/src/verification/visual_auditor.py.
//
// Direct correspondences:
//   _load_and_preprocess     → preprocessPair  (aspect-ratio crop + resize)
//   _calculate_ssim          → calculateSsim
//   _calculate_pixel_similarity → calculatePixelSimilarity
//   _pixel_diff_score        → pixelmatch + pixelMatchScore
//   _calculate_overall_score → compositeScore (no vision in MVP, so 0.5/0.5)

import pixelmatch from "pixelmatch";
import { PNG } from "pngjs";
import sharp from "sharp";
import { ssim as computeSsim } from "ssim.js";
import {
  ASPECT_RATIO_MISMATCH_PCT,
  MIN_SCREENSHOT_BYTES,
  PIXELMATCH_THRESHOLD,
  type DiffResult,
} from "./types.js";
import { log } from "./utils.js";

interface RawImage {
  width: number;
  height: number;
  data: Buffer;
}

async function decodeToRgba(buf: Buffer): Promise<RawImage> {
  // sharp gives us reliable RGBA at known dimensions, including for non-PNG inputs.
  const { data, info } = await sharp(buf)
    .ensureAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true });
  return { width: info.width, height: info.height, data };
}

async function rawToPngBuffer(img: RawImage): Promise<Buffer> {
  return sharp(img.data, {
    raw: { width: img.width, height: img.height, channels: 4 },
  })
    .png()
    .toBuffer();
}

// Ported from visual_auditor.py:206-262 — _load_and_preprocess.
// If aspect ratios differ by more than ASPECT_RATIO_MISMATCH_PCT (10%), crop the
// taller/wider image to match before resizing. Otherwise just resize.
async function preprocessPair(
  before: Buffer,
  after: Buffer
): Promise<{
  beforeRgba: RawImage;
  afterRgba: RawImage;
  dimensionMismatch: boolean;
  aspectRatioCropApplied: boolean;
}> {
  const baseMeta = await sharp(before).metadata();
  const headMeta = await sharp(after).metadata();
  const bw = baseMeta.width ?? 0;
  const bh = baseMeta.height ?? 0;
  const hw = headMeta.width ?? 0;
  const hh = headMeta.height ?? 0;

  if (!bw || !bh || !hw || !hh) {
    throw new Error("Could not read screenshot dimensions");
  }

  const dimensionMismatch = bw !== hw || bh !== hh;
  let aspectRatioCropApplied = false;
  let beforeBuf = before;
  let afterBuf = after;

  if (dimensionMismatch) {
    const baseAr = bw / bh;
    const headAr = hw / hh;
    const arDiff = Math.abs(baseAr - headAr) / Math.max(baseAr, headAr);

    if (arDiff > ASPECT_RATIO_MISMATCH_PCT) {
      // Crop the BEFORE image to match the AFTER aspect ratio, then resize to AFTER's
      // size. This mirrors visual_auditor.py — it treats the "rendered" (head) as
      // canonical and aligns the comparison target to it.
      log(
        `[diff] aspect ratio mismatch ${bw}×${bh} (${baseAr.toFixed(2)}) vs ` +
          `${hw}×${hh} (${headAr.toFixed(2)}), diff=${(arDiff * 100).toFixed(0)}% — cropping before`
      );
      if (baseAr < headAr) {
        // Before is too tall — crop from top, keep bottom (matches visual_auditor.py:240-246).
        const cropH = Math.min(Math.round(bw / headAr), bh);
        const cropTop = bh - cropH;
        beforeBuf = await sharp(before)
          .extract({ left: 0, top: cropTop, width: bw, height: cropH })
          .toBuffer();
      } else {
        // Before is too wide — crop sides centered (matches visual_auditor.py:247-253).
        const cropW = Math.min(Math.round(bh * headAr), bw);
        const cropLeft = Math.floor((bw - cropW) / 2);
        beforeBuf = await sharp(before)
          .extract({ left: cropLeft, top: 0, width: cropW, height: bh })
          .toBuffer();
      }
      // Now resize cropped before to head dimensions (Lanczos, like PIL.LANCZOS).
      beforeBuf = await sharp(beforeBuf)
        .resize(hw, hh, { kernel: "lanczos3", fit: "fill" })
        .toBuffer();
      aspectRatioCropApplied = true;
    } else {
      // Same-AR mismatch: resize head to match base (visual_auditor.py:258-260).
      log(`[diff] resizing head ${hw}×${hh} → ${bw}×${bh}`);
      afterBuf = await sharp(after)
        .resize(bw, bh, { kernel: "lanczos3", fit: "fill" })
        .toBuffer();
    }
  }

  const beforeRgba = await decodeToRgba(beforeBuf);
  const afterRgba = await decodeToRgba(afterBuf);

  // Final safety net — if for any reason dimensions still mismatch, force-resize.
  if (
    beforeRgba.width !== afterRgba.width ||
    beforeRgba.height !== afterRgba.height
  ) {
    const w = Math.min(beforeRgba.width, afterRgba.width);
    const h = Math.min(beforeRgba.height, afterRgba.height);
    const reb = await sharp(beforeBuf)
      .resize(w, h, { kernel: "lanczos3", fit: "fill" })
      .ensureAlpha()
      .raw()
      .toBuffer({ resolveWithObject: true });
    const reh = await sharp(afterBuf)
      .resize(w, h, { kernel: "lanczos3", fit: "fill" })
      .ensureAlpha()
      .raw()
      .toBuffer({ resolveWithObject: true });
    return {
      beforeRgba: { width: reb.info.width, height: reb.info.height, data: reb.data },
      afterRgba: { width: reh.info.width, height: reh.info.height, data: reh.data },
      dimensionMismatch: true,
      aspectRatioCropApplied,
    };
  }

  return { beforeRgba, afterRgba, dimensionMismatch, aspectRatioCropApplied };
}

// Ported from visual_auditor.py:284-294 — _calculate_pixel_similarity.
// 1.0 - sum(|a - b|) / (size * 255). RGB only, ignore alpha.
function calculatePixelSimilarity(a: RawImage, b: RawImage): number {
  if (a.width !== b.width || a.height !== b.height) return 0;
  let totalDiff = 0;
  const da = a.data;
  const db = b.data;
  const len = da.length;
  for (let i = 0; i < len; i += 4) {
    totalDiff +=
      Math.abs(da[i] - db[i]) +
      Math.abs(da[i + 1] - db[i + 1]) +
      Math.abs(da[i + 2] - db[i + 2]);
  }
  const totalRgbValues = a.width * a.height * 3;
  const maxDiff = totalRgbValues * 255;
  const sim = 1 - totalDiff / maxDiff;
  return Math.max(0, Math.min(1, sim));
}

// Ported from visual_auditor.py:264-282 — _calculate_ssim, on grayscale.
// ssim.js works on RGBA buffers; we convert to grayscale RGBA so each channel is
// equal (Y in BT.601), giving us the same answer as PIL grayscale + skimage SSIM.
function calculateSsim(a: RawImage, b: RawImage): number {
  if (a.width !== b.width || a.height !== b.height) return 0;
  const grayA = toGrayscaleRgba(a);
  const grayB = toGrayscaleRgba(b);
  try {
    const result = computeSsim(
      { data: grayA, width: a.width, height: a.height },
      { data: grayB, width: b.width, height: b.height },
      { downsample: "fast" } // matches the spirit of visual_auditor.py's quick SSIM
    );
    return Math.max(0, Math.min(1, result.mssim));
  } catch (err) {
    log(`[diff] SSIM failed: ${(err as Error).message}`);
    return 0;
  }
}

function toGrayscaleRgba(img: RawImage): Uint8ClampedArray {
  const out = new Uint8ClampedArray(img.data.length);
  for (let i = 0; i < img.data.length; i += 4) {
    const r = img.data[i];
    const g = img.data[i + 1];
    const b = img.data[i + 2];
    // BT.601 luma — same coefficients used by skimage.color.rgb2gray
    const y = Math.round(0.299 * r + 0.587 * g + 0.114 * b);
    out[i] = y;
    out[i + 1] = y;
    out[i + 2] = y;
    out[i + 3] = 255;
  }
  return out;
}

export async function diffPngs(
  before: Buffer,
  after: Buffer,
  threshold: number = PIXELMATCH_THRESHOLD
): Promise<DiffResult> {
  // Ported from visual_auditor.py — min size check from prompt requirement.
  // <100KB on a real screenshot almost always means thumbnail / blank / error page.
  const suspectedInvalidInput =
    before.byteLength < MIN_SCREENSHOT_BYTES ||
    after.byteLength < MIN_SCREENSHOT_BYTES;
  if (suspectedInvalidInput) {
    log(
      `[diff] WARN: suspected broken input — before=${before.byteLength}B after=${after.byteLength}B`
    );
  }

  const { beforeRgba, afterRgba, dimensionMismatch, aspectRatioCropApplied } =
    await preprocessPair(before, after);

  const width = beforeRgba.width;
  const height = afterRgba.height;
  const totalPixels = width * height;

  // pixelmatch needs a writable diff buffer the same shape as inputs.
  const diffPng = new PNG({ width, height });
  const changedPixels = pixelmatch(
    beforeRgba.data,
    afterRgba.data,
    diffPng.data,
    width,
    height,
    {
      threshold, // matches visual_auditor.py:365 (0.1)
      includeAA: false,
      alpha: 0.3,
      diffColor: [255, 0, 0],
    }
  );

  // Build the human-friendly overlay: a copy of "after" with red marks where
  // pixelmatch flagged differences. Same idea as generate_diff_image() but we
  // overlay onto AFTER instead of computing PIL.ImageChops.difference, because
  // AFTER + red marks is much clearer in a PR comment.
  const overlay: RawImage = {
    width,
    height,
    data: Buffer.from(afterRgba.data),
  };
  for (let i = 0; i < diffPng.data.length; i += 4) {
    if (
      diffPng.data[i] === 255 &&
      diffPng.data[i + 1] === 0 &&
      diffPng.data[i + 2] === 0
    ) {
      overlay.data[i] = 255;
      overlay.data[i + 1] = 0;
      overlay.data[i + 2] = 0;
      overlay.data[i + 3] = 255;
    }
  }
  const diffImage = await rawToPngBuffer(overlay);

  // Scoring — three views of "how similar are these?":
  //   pixelMatchScore        : visual_auditor.py:369 — 1 - changed/total
  //   pixelSimilarityScore   : visual_auditor.py:290 — 1 - sum|diff|/(size·255)
  //   ssimScore              : visual_auditor.py:274 — structural similarity
  const pixelMatchScore = Math.max(0, Math.min(1, 1 - changedPixels / totalPixels));
  const pixelSimilarityScore = calculatePixelSimilarity(beforeRgba, afterRgba);
  const ssimScore = calculateSsim(beforeRgba, afterRgba);

  // visual_auditor.py:478-482 — without vision, weight structural & pixel equally.
  // We interpret "pixel" as pixelSimilarityScore (matches Python's pixel_score).
  const compositeScore = ssimScore * 0.5 + pixelSimilarityScore * 0.5;

  const percentChanged = (changedPixels / totalPixels) * 100;

  return {
    diffImage,
    percentChanged,
    changedPixels,
    totalPixels,
    width,
    height,
    pixelMatchScore,
    pixelSimilarityScore,
    ssimScore,
    compositeScore,
    dimensionMismatch,
    aspectRatioCropApplied,
    suspectedInvalidInput,
  };
}
