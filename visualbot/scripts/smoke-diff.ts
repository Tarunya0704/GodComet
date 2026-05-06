// Smoke test for src/differ.ts.
//
// Usage:
//   npx tsx scripts/smoke-diff.ts <before.png> <after.png>
//
// Decodes both PNGs, runs the full diff pipeline (SSIM + pixelmatch +
// AR-crop), writes the overlay to diff-out.png, and prints the scores.

import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { diffPngs } from "../src/differ.js";

async function main(): Promise<void> {
  const [, , beforeArg, afterArg] = process.argv;
  if (!beforeArg || !afterArg) {
    console.error("usage: smoke-diff.ts <before.png> <after.png>");
    process.exit(1);
  }

  const beforePath = resolve(beforeArg);
  const afterPath = resolve(afterArg);
  const before = readFileSync(beforePath);
  const after = readFileSync(afterPath);

  console.log(`before: ${beforePath} (${before.byteLength.toLocaleString()} bytes)`);
  console.log(`after:  ${afterPath} (${after.byteLength.toLocaleString()} bytes)`);
  console.log("");

  const start = Date.now();
  const r = await diffPngs(before, after);
  const ms = Date.now() - start;

  const outPath = resolve("diff-out.png");
  writeFileSync(outPath, r.diffImage);

  const fmtPct = (n: number) => (n * 100).toFixed(2) + "%";
  console.log(`diff computed in ${ms}ms`);
  console.log("");
  console.log("scores:");
  console.log(`  pixel change          ${r.percentChanged.toFixed(3)}%`);
  console.log(`  pixelmatch score      ${fmtPct(r.pixelMatchScore)}`);
  console.log(`  pixel similarity      ${fmtPct(r.pixelSimilarityScore)}`);
  console.log(`  SSIM                  ${fmtPct(r.ssimScore)}`);
  console.log(`  composite             ${fmtPct(r.compositeScore)}`);
  console.log("");
  console.log("metadata:");
  console.log(`  diff dimensions       ${r.width} × ${r.height}`);
  console.log(`  changed pixels        ${r.changedPixels.toLocaleString()} / ${r.totalPixels.toLocaleString()}`);
  console.log(`  dimension mismatch    ${r.dimensionMismatch}`);
  console.log(`  AR crop applied       ${r.aspectRatioCropApplied}`);
  console.log(`  suspected invalid     ${r.suspectedInvalidInput}`);
  console.log("");
  console.log(`diff overlay written to ${outPath} (${r.diffImage.byteLength.toLocaleString()} bytes)`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
