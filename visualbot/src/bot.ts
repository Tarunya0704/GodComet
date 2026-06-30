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
  type FailedRoute,
  type PageDiff,
  type ScreenshotOutcome,
  type StageTiming,
  type UnchangedRoute,
} from "./types.js";
import { readConfig } from "./config.js";
import { detectRoutes, type DetectionResult } from "./route-detector.js";

const PIPELINE_TIMEOUT_MS = 5 * 60 * 1000;

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

// Fetches the list of files changed in the PR (first 100).
// Used by the route auto-detector before the clone step.
async function getPrChangedFiles(
  context: Context<"pull_request">,
  owner: string,
  repo: string,
  prNumber: number
): Promise<string[]> {
  const { data } = await context.octokit.pulls.listFiles({
    owner,
    repo,
    pull_number: prNumber,
    per_page: 100,
  });
  return data.map(f => f.filename);
}

async function buildAndShoot(
  repoDir: string,
  side: "base" | "head",
  routes: string[],
  timings: StageTiming[]
): Promise<Map<string, ScreenshotOutcome>> {
  const port = await findAvailablePort();
  let server: RunningServer | null = null;
  try {
    server = await timed(`${side}.build+start`, () => buildAndStart(repoDir, port), timings);
    return await timed(
      `${side}.screenshot`,
      () =>
        screenshotPages(server!.port, {
          pages: routes,
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

    // Fetch the PR file list early — it's a cheap API call and feeds the
    // route auto-detector that runs after the clone.
    currentStage = "files";
    const prChangedFiles = await timed(
      "files",
      () => getPrChangedFiles(context, owner, repo, prNumber),
      timings
    );
    log(`[pipeline] PR has ${prChangedFiles.length} changed file(s)`);

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

    // Route resolution — manual config wins, auto-detect is the fallback.
    currentStage = "routes";
    let routes: string[];
    let detection: DetectionResult | null = null;

    const manualConfig = readConfig(headDir);
    if (manualConfig) {
      routes = manualConfig.routes;
      log(`[pipeline] using .shirodiff.yml routes: ${routes.join(", ")}`);
    } else {
      detection = await timed(
        "routes",
        async () => detectRoutes(prChangedFiles, headDir),
        timings
      );
      routes = detection.routes;
    }

    currentStage = "base";
    const baseShots = await buildAndShoot(baseDir, "base", routes, timings);

    currentStage = "head";
    const headShots = await buildAndShoot(headDir, "head", routes, timings);

    currentStage = "diff";
    const diffs: PageDiff[] = [];
    const unchangedRoutes: UnchangedRoute[] = [];
    const failedRoutes: FailedRoute[] = [];

    await timed(
      "diff",
      async () => {
        for (const path of routes) {
          // Per-route error isolation: a bad route records a failure and
          // continues — it never kills the rest of the run or the comment.
          try {
            const baseOutcome = baseShots.get(path);
            const headOutcome = headShots.get(path);

            if (!baseOutcome || !headOutcome) {
              failedRoutes.push({ pagePath: path, error: "Screenshot missing from result map" });
              continue;
            }
            if (!baseOutcome.ok) {
              failedRoutes.push({ pagePath: path, error: `base: ${baseOutcome.error}` });
              continue;
            }
            if (!headOutcome.ok) {
              failedRoutes.push({ pagePath: path, error: `head: ${headOutcome.error}` });
              continue;
            }

            const before = baseOutcome.data;
            const after = headOutcome.data;

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
            } else {
              unchangedRoutes.push({
                pagePath: path,
                diff: diffResult,
                viewport: before.viewportDimensions,
              });
            }
          } catch (err) {
            const msg = err instanceof Error ? err.message : String(err);
            logError(`[diff] ${path} failed: ${msg}`);
            failedRoutes.push({ pagePath: path, error: msg });
          }
        }
      },
      timings
    );

    // Build a subtle footer note so reviewers know how routes were picked.
    const detectionNote = buildDetectionNote(detection, manualConfig !== null);

    currentStage = "comment";
    if (diffs.length === 0 && failedRoutes.length === 0) {
      await timed(
        "comment.no-change",
        () => postNoChangeComment(context, target, pendingId!, unchangedRoutes, detectionNote),
        timings
      );
    } else {
      await timed(
        "comment.change",
        () =>
          postChangeComment(
            context,
            target,
            pendingId!,
            diffs,
            unchangedRoutes,
            failedRoutes,
            detectionNote
          ),
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

function buildDetectionNote(
  detection: DetectionResult | null,
  hadManualConfig: boolean
): string | undefined {
  if (hadManualConfig) return undefined;
  if (!detection) return undefined;

  const parts: string[] = [
    `Routes auto-detected · ${detection.framework}`,
  ];
  if (detection.hadGlobalChanges) {
    parts.push("global file(s) changed → / included");
  }
  if (detection.skippedDynamic.length > 0) {
    const names = detection.skippedDynamic.slice(0, 3).join(", ");
    const extra = detection.skippedDynamic.length > 3
      ? ` +${detection.skippedDynamic.length - 3} more`
      : "";
    parts.push(`dynamic routes skipped: ${names}${extra}`);
  }
  return parts.join(" · ");
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
