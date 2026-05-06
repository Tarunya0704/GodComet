// Pipeline orchestrator.
//
// Stage-by-stage logging & timing pattern is borrowed from GodComet's
// workflow_executor — every external operation runs through `timed()` so we
// can report stage timings in the PR comment when something is slow, and so
// that errors are tagged with the stage name (mirrors how GodComet's executor
// pushes WebSocket "stage_started/stage_failed" events).

import type { Context } from "probot";
import {
  cleanupTempDir,
  createTempDir,
  findAvailablePort,
  killProcess,
  log,
  logError,
  timed,
  withTimeout,
} from "./utils.js";
import type { StageError } from "./utils.js";
import { cloneAtSha } from "./clone.js";
import { buildAndStart, type RunningServer } from "./builder.js";
import { screenshotPages } from "./screenshotter.js";
import { diffPngs } from "./differ.js";
import {
  postPendingComment,
  postErrorComment,
  postNoChangeComment,
  postChangeComment,
} from "./commenter.js";
import {
  DEFAULT_VIEWPORT,
  VISUAL_CHANGE_THRESHOLD_PCT,
  type PageDiff,
  type ScreenshotResult,
  type StageTiming,
} from "./types.js";

const PIPELINE_TIMEOUT_MS = 5 * 60 * 1000;
const PAGES_TO_SHOOT = ["/"];

async function getInstallationToken(
  context: Context<"pull_request">
): Promise<string> {
  const installationId = context.payload.installation?.id;
  if (!installationId) {
    throw new Error("Webhook payload missing installation id");
  }
  const { data } = await context.octokit.apps.createInstallationAccessToken({
    installation_id: installationId,
  });
  return data.token;
}

async function buildAndShoot(
  repoDir: string,
  side: "base" | "head",
  timings: StageTiming[]
): Promise<Map<string, ScreenshotResult>> {
  const port = await findAvailablePort();
  let server: RunningServer | null = null;
  try {
    server = await timed(`${side}.build+start`, () => buildAndStart(repoDir, port), timings);
    return await timed(
      `${side}.screenshot`,
      () =>
        screenshotPages(server!.port, {
          pages: PAGES_TO_SHOOT,
          viewport: DEFAULT_VIEWPORT,
          pageTimeoutMs: 30_000,
          maxRetries: 2,
        }),
      timings
    );
  } finally {
    if (server) await killProcess(server.process);
  }
}

async function runPipeline(context: Context<"pull_request">): Promise<void> {
  const pr = context.payload.pull_request;
  const owner = context.payload.repository.owner.login;
  const repo = context.payload.repository.name;
  const prNumber = pr.number;
  const baseSha = pr.base.sha;
  const headSha = pr.head.sha;
  const target = { owner, repo, prNumber };

  log(
    `PR #${prNumber} ${owner}/${repo}: base ${baseSha.slice(0, 7)} head ${headSha.slice(0, 7)}`
  );

  const timings: StageTiming[] = [];
  let pendingId: number | null = null;
  let currentStage: string | null = null;

  try {
    pendingId = await timed(
      "comment.pending",
      () => postPendingComment(context, target),
      timings
    );

    currentStage = "auth";
    const installationToken = await timed(
      "auth",
      () => getInstallationToken(context),
      timings
    );

    currentStage = "tempdir";
    const [baseDir, headDir] = await timed(
      "tempdir",
      () =>
        Promise.all([
          createTempDir(prNumber, "base"),
          createTempDir(prNumber, "head"),
        ]),
      timings
    );

    currentStage = "clone";
    await timed(
      "clone",
      () =>
        Promise.all([
          cloneAtSha({
            owner,
            repo,
            sha: baseSha,
            installationToken,
            targetDir: baseDir,
          }),
          cloneAtSha({
            owner,
            repo,
            sha: headSha,
            installationToken,
            targetDir: headDir,
          }),
        ]),
      timings
    );

    currentStage = "base";
    const baseShots = await buildAndShoot(baseDir, "base", timings);

    currentStage = "head";
    const headShots = await buildAndShoot(headDir, "head", timings);

    currentStage = "diff";
    const diffs: PageDiff[] = [];
    let firstNoChange = "";
    await timed(
      "diff",
      async () => {
        for (const path of PAGES_TO_SHOOT) {
          const before = baseShots.get(path);
          const after = headShots.get(path);
          if (!before || !after) {
            log(`[diff] missing screenshot for ${path}, skipping`);
            continue;
          }
          // Diff on viewport-only — render_engine.py learned that fixed-viewport
          // gives more meaningful comparisons than full-page (page height
          // varies independently of UI changes).
          const diffResult = await diffPngs(before.viewport, after.viewport);
          log(
            `[diff] ${path}: ${diffResult.percentChanged.toFixed(3)}% changed · ` +
              `SSIM ${(diffResult.ssimScore * 100).toFixed(2)}% · ` +
              `composite ${(diffResult.compositeScore * 100).toFixed(2)}%`
          );
          if (diffResult.percentChanged >= VISUAL_CHANGE_THRESHOLD_PCT) {
            // Use full-page PNGs for the comment (more useful for humans).
            diffs.push({
              pagePath: path,
              beforePng: before.fullPage,
              afterPng: after.fullPage,
              diff: diffResult,
              viewport: before.viewportDimensions,
            });
          } else if (!firstNoChange) {
            firstNoChange =
              `_Pixel change ${diffResult.percentChanged.toFixed(3)}% · ` +
              `SSIM ${(diffResult.ssimScore * 100).toFixed(2)}% · ` +
              `Composite ${(diffResult.compositeScore * 100).toFixed(2)}%_`;
          }
        }
      },
      timings
    );

    currentStage = "comment";
    if (diffs.length === 0) {
      await timed(
        "comment.no-change",
        () =>
          postNoChangeComment(
            context,
            target,
            pendingId!,
            firstNoChange ||
              "_All pages below the change threshold._"
          ),
        timings
      );
    } else {
      await timed(
        "comment.change",
        () => postChangeComment(context, target, pendingId!, diffs),
        timings
      );
    }

    log(
      `[pipeline] PR #${prNumber} done. timings:\n` +
        timings.map((t) => `  ${t.stage}: ${t.ms}ms`).join("\n")
    );
  } catch (err) {
    const stage =
      (err as StageError).stage ?? currentStage ?? "unknown";
    const msg = err instanceof Error ? err.message : String(err);
    logError(`pipeline failed at stage="${stage}":`, msg);
    try {
      await postErrorComment(context, target, pendingId, stage, msg, timings);
    } catch (commentErr) {
      logError("failed to post error comment:", commentErr);
    }
  } finally {
    await cleanupTempDir(prNumber);
  }
}

export async function handlePR(context: Context<"pull_request">): Promise<void> {
  try {
    await withTimeout(runPipeline(context), PIPELINE_TIMEOUT_MS, "PR pipeline");
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    const stage = (err as StageError).stage ?? "pipeline";
    logError("handlePR top-level error:", msg);
    const owner = context.payload.repository.owner.login;
    const repo = context.payload.repository.name;
    const prNumber = context.payload.pull_request.number;
    try {
      await postErrorComment(context, { owner, repo, prNumber }, null, stage, msg);
    } catch {
      // already logged
    }
  }
}
