// PR commenter & asset uploader.
//
// Patterns ported from mcp-automation/src/tools/github_tool.py and the
// rate-limit logic in mcp-automation/src/tools/production_figma_converter.py:
//
//   - Every GitHub API call goes through a 429/5xx-aware retry wrapper using
//     `base_wait * 2^attempt` with base_wait=30s — exact match for
//     production_figma_converter.py:1582-1587.
//   - The change-report comment now surfaces ALL three diff scores from
//     visual_auditor.py (pixel match, pixel similarity, SSIM) plus composite,
//     and explicitly states the viewport at which screenshots were taken.
//   - Comment uses ✂ markers when AR-crop or dimension padding was applied so
//     the reader knows the diff was normalized.

import type { Context } from "probot";
import { log } from "./utils.js";
import { isRetriableHttpError, retryWithBackoff } from "./utils.js";
import type { PageDiff } from "./types.js";

interface CommentTarget {
  owner: string;
  repo: string;
  prNumber: number;
}

const ASSET_BRANCH = "visualbot-assets";

type Octokit = Context["octokit"];

// Wraps a GitHub API call with the GodComet exponential-backoff retry pattern.
// Only retries on rate-limit (429), transient 5xx, or network errors —
// everything else bubbles immediately so we don't mask logic bugs.
function gh<T>(label: string, fn: () => Promise<T>): Promise<T> {
  return retryWithBackoff(fn, {
    maxAttempts: 4, // 4 attempts: 0, 30s, 60s, 120s — caps at ~3.5min total
    baseDelayMs: 30_000,
    label: `gh.${label}`,
    shouldRetry: isRetriableHttpError,
  });
}

async function ensureAssetBranch(
  octokit: Octokit,
  owner: string,
  repo: string
): Promise<string> {
  try {
    const { data: ref } = await gh("getRef", () =>
      octokit.git.getRef({ owner, repo, ref: `heads/${ASSET_BRANCH}` })
    );
    return ref.object.sha;
  } catch (err: unknown) {
    const status = (err as { status?: number }).status;
    if (status !== 404) throw err;
  }

  // GitHub's createTree rejects `tree: []` with 422 "Invalid tree info."
  // Seed the branch with a placeholder README so the initial tree is non-empty.
  // Sequence: create blob → create tree referencing blob → create orphan commit
  // → create branch ref.
  const placeholder =
    "# VisualBot assets\n\n" +
    "This branch is auto-managed by VisualBot — it stores before/after/diff " +
    "PNGs referenced by PR comments. Do not edit manually.\n";

  const { data: blob } = await gh("createBlob", () =>
    octokit.git.createBlob({
      owner,
      repo,
      content: Buffer.from(placeholder, "utf-8").toString("base64"),
      encoding: "base64",
    })
  );
  const { data: tree } = await gh("createTree", () =>
    octokit.git.createTree({
      owner,
      repo,
      tree: [
        { path: "README.md", mode: "100644", type: "blob", sha: blob.sha },
      ],
    })
  );
  const { data: commit } = await gh("createCommit", () =>
    octokit.git.createCommit({
      owner,
      repo,
      message: "VisualBot: initialize assets branch",
      tree: tree.sha,
      parents: [],
    })
  );
  try {
    await gh("createRef", () =>
      octokit.git.createRef({
        owner,
        repo,
        ref: `refs/heads/${ASSET_BRANCH}`,
        sha: commit.sha,
      })
    );
    log(`[commenter] created orphan branch ${ASSET_BRANCH} on ${owner}/${repo}`);
    return commit.sha;
  } catch (err: unknown) {
    // Race: another concurrent uploadAsset() got here first and created the
    // branch. GitHub returns 422 with "Reference already exists" — benign,
    // the branch exists now, which is what we wanted.
    const e = err as { status?: number; message?: string };
    if (e.status === 422 && (e.message ?? "").includes("Reference already exists")) {
      log(`[commenter] branch ${ASSET_BRANCH} was concurrently created — proceeding`);
      const { data: ref } = await gh("getRef.after-race", () =>
        octokit.git.getRef({ owner, repo, ref: `heads/${ASSET_BRANCH}` })
      );
      return ref.object.sha;
    }
    throw err;
  }
}

async function uploadAsset(
  octokit: Octokit,
  owner: string,
  repo: string,
  path: string,
  png: Buffer,
  message: string
): Promise<string> {
  await ensureAssetBranch(octokit, owner, repo);

  let existingSha: string | undefined;
  try {
    const { data } = await gh("getContent", () =>
      octokit.repos.getContent({ owner, repo, path, ref: ASSET_BRANCH })
    );
    if (!Array.isArray(data) && "sha" in data) {
      existingSha = data.sha;
    }
  } catch (err: unknown) {
    const status = (err as { status?: number }).status;
    if (status !== 404) throw err;
  }

  await gh("createOrUpdateFileContents", () =>
    octokit.repos.createOrUpdateFileContents({
      owner,
      repo,
      path,
      branch: ASSET_BRANCH,
      message,
      content: png.toString("base64"),
      sha: existingSha,
    })
  );

  return `https://raw.githubusercontent.com/${owner}/${repo}/${ASSET_BRANCH}/${path}`;
}

export async function postPendingComment(
  context: Context<"pull_request">,
  target: CommentTarget
): Promise<number> {
  const { data } = await gh("createComment.pending", () =>
    context.octokit.issues.createComment({
      owner: target.owner,
      repo: target.repo,
      issue_number: target.prNumber,
      body:
        "## 👁 VisualBot — ⏳ Analyzing visual changes...\n\n" +
        "Cloning, building, and screenshotting both versions of your PR.\n\n" +
        "<sub>VisualBot • Catch visual regressions before they ship</sub>",
    })
  );
  return data.id;
}

export async function updateComment(
  context: Context<"pull_request">,
  target: CommentTarget,
  commentId: number,
  body: string
): Promise<void> {
  await gh("updateComment", () =>
    context.octokit.issues.updateComment({
      owner: target.owner,
      repo: target.repo,
      comment_id: commentId,
      body,
    })
  );
}

export async function postErrorComment(
  context: Context<"pull_request">,
  target: CommentTarget,
  commentId: number | null,
  stage: string | null,
  message: string,
  timings?: { stage: string; ms: number }[]
): Promise<void> {
  // Stage-specific error message — the developer should immediately know
  // whether their PR's build broke vs VisualBot's infra hiccuped.
  const header = stage
    ? `## 👁 VisualBot — ❌ Failed at \`${stage}\``
    : "## 👁 VisualBot — ❌ Error";
  const timingBlock =
    timings && timings.length
      ? "\n\n**Stage timings:**\n" +
        timings.map((t) => `- \`${t.stage}\` — ${t.ms}ms`).join("\n")
      : "";
  const body =
    `${header}\n\nVisualBot encountered an error while analyzing this PR:\n\n` +
    "```\n" +
    message.slice(0, 4000) +
    "\n```" +
    timingBlock +
    "\n\n<sub>VisualBot • Catch visual regressions before they ship</sub>";
  if (commentId) {
    await updateComment(context, target, commentId, body);
  } else {
    await gh("createComment.error", () =>
      context.octokit.issues.createComment({
        owner: target.owner,
        repo: target.repo,
        issue_number: target.prNumber,
        body,
      })
    );
  }
}

export async function postNoChangeComment(
  context: Context<"pull_request">,
  target: CommentTarget,
  commentId: number,
  scoresLine: string
): Promise<void> {
  const body =
    "## 👁 VisualBot — ✅ No Visual Changes\n\n" +
    "No significant visual differences detected in this PR.\n\n" +
    `${scoresLine}\n\n` +
    "---\n" +
    "<sub>VisualBot • Catch visual regressions before they ship</sub>";
  await updateComment(context, target, commentId, body);
}

function fmtPct(n: number): string {
  return (n * 100).toFixed(2) + "%";
}

export async function postChangeComment(
  context: Context<"pull_request">,
  target: CommentTarget,
  commentId: number,
  diffs: PageDiff[]
): Promise<void> {
  const { owner, repo, prNumber } = target;
  const headSha = context.payload.pull_request.head.sha.slice(0, 7);

  const sections: string[] = [];
  for (const d of diffs) {
    const safePath = d.pagePath.replace(/[^a-zA-Z0-9_-]/g, "_") || "root";
    const base = `visualbot/pr-${prNumber}/${headSha}/${safePath}`;

    // Serialized, not Promise.all: createOrUpdateFileContents advances the
    // branch HEAD with a new commit each call. Parallel calls race on the
    // branch sha and only one wins per round-trip, so we'd just collect
    // 409 conflicts. Three sequential round-trips is ~1s extra latency —
    // worth it for correctness.
    const beforeUrl = await uploadAsset(
      context.octokit,
      owner,
      repo,
      `${base}/before.png`,
      d.beforePng,
      `VisualBot PR#${prNumber} ${d.pagePath} before`
    );
    const afterUrl = await uploadAsset(
      context.octokit,
      owner,
      repo,
      `${base}/after.png`,
      d.afterPng,
      `VisualBot PR#${prNumber} ${d.pagePath} after`
    );
    const diffUrl = await uploadAsset(
      context.octokit,
      owner,
      repo,
      `${base}/diff.png`,
      d.diff.diffImage,
      `VisualBot PR#${prNumber} ${d.pagePath} diff`
    );

    // GodComet's audit returns three independent scores; expose all three so
    // a developer reading the comment can sanity-check pixel-vs-structural
    // disagreement (e.g. font swap → big SSIM drop, small pixel change).
    const flags: string[] = [];
    if (d.diff.aspectRatioCropApplied) flags.push("✂ AR-cropped");
    if (d.diff.dimensionMismatch) flags.push("📐 dim-normalized");
    if (d.diff.suspectedInvalidInput) flags.push("⚠ small-screenshot");
    const flagLine = flags.length ? `\n_${flags.join(" · ")}_` : "";

    sections.push(
      `### \`${d.pagePath}\`\n\n` +
        `| Before | After | Diff |\n` +
        `|--------|-------|------|\n` +
        `| ![before](${beforeUrl}) | ![after](${afterUrl}) | ![diff](${diffUrl}) |\n\n` +
        `**Pixel change: ${d.diff.percentChanged.toFixed(2)}%** ` +
        `(${d.diff.changedPixels.toLocaleString()} of ${d.diff.totalPixels.toLocaleString()} px) · ` +
        `**SSIM:** ${fmtPct(d.diff.ssimScore)} · ` +
        `**Pixel sim:** ${fmtPct(d.diff.pixelSimilarityScore)} · ` +
        `**Composite:** ${fmtPct(d.diff.compositeScore)}\n\n` +
        `<sub>Viewport: ${d.viewport.width}×${d.viewport.height} · ` +
        `Diffed at ${d.diff.width}×${d.diff.height}${flagLine}</sub>\n`
    );
  }

  const body =
    `## 👁 VisualBot — Visual Change Report\n\n` +
    `**PR #${prNumber}** has visual changes on ${diffs.length} page(s).\n\n` +
    sections.join("\n---\n\n") +
    `\n---\n<sub>VisualBot • Catch visual regressions before they ship · ` +
    `Scores ported from GodComet's visual auditor (SSIM + pixelmatch + pixel-sim composite).</sub>`;

  await updateComment(context, target, commentId, body);
}
