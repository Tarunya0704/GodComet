import { createServer } from "node:net";
import { mkdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { request } from "node:http";
import treeKill from "tree-kill";
import type { ChildProcess } from "node:child_process";

export function log(...args: unknown[]): void {
  const ts = new Date().toISOString();
  console.log(`[VisualBot ${ts}]`, ...args);
}

export function logError(...args: unknown[]): void {
  const ts = new Date().toISOString();
  console.error(`[VisualBot ${ts}] ERROR`, ...args);
}

export function findAvailablePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const srv = createServer();
    srv.unref();
    srv.on("error", reject);
    srv.listen(0, () => {
      const addr = srv.address();
      if (addr && typeof addr === "object") {
        const port = addr.port;
        srv.close(() => resolve(port));
      } else {
        srv.close();
        reject(new Error("Could not determine free port"));
      }
    });
  });
}

export function tempRoot(prId: string | number): string {
  return join(tmpdir(), "visualbot", String(prId));
}

export async function createTempDir(
  prId: string | number,
  type: "base" | "head"
): Promise<string> {
  const dir = join(tempRoot(prId), type);
  await mkdir(dir, { recursive: true });
  return dir;
}

export async function cleanupTempDir(prId: string | number): Promise<void> {
  const dir = tempRoot(prId);
  try {
    await rm(dir, { recursive: true, force: true });
  } catch (err) {
    logError("cleanupTempDir failed", dir, err);
  }
}

export function waitForServer(port: number, timeoutMs = 60_000): Promise<void> {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const tryOnce = () => {
      const req = request(
        { host: "127.0.0.1", port, path: "/", method: "GET", timeout: 2000 },
        (res) => {
          res.resume();
          if (res.statusCode && res.statusCode < 500) {
            resolve();
          } else {
            schedule();
          }
        }
      );
      req.on("error", schedule);
      req.on("timeout", () => {
        req.destroy();
        schedule();
      });
      req.end();
    };
    const schedule = () => {
      if (Date.now() - start > timeoutMs) {
        reject(
          new Error(`Server on port ${port} did not become ready within ${timeoutMs}ms`)
        );
        return;
      }
      setTimeout(tryOnce, 500);
    };
    tryOnce();
  });
}

export function killProcess(proc: ChildProcess | null | undefined): Promise<void> {
  return new Promise((resolve) => {
    if (!proc || proc.killed || proc.pid === undefined) {
      resolve();
      return;
    }
    const pid = proc.pid;

    const fallbackDirectKill = () => {
      // On Linux we spawn child processes with `detached: true`, so the child
      // is its own process-group leader. Killing the negative pid signals the
      // entire group — equivalent to what tree-kill is trying to do, but
      // without shelling out to `ps`.
      try {
        if (process.platform !== "win32") {
          process.kill(-pid, "SIGTERM");
        } else {
          proc.kill("SIGKILL");
        }
      } catch (err) {
        // Process already dead, or no permission, or pgid doesn't exist.
        // Either way, our last-ditch try-direct-kill:
        try {
          proc.kill("SIGKILL");
        } catch {
          /* give up silently — better than crashing the bot */
        }
      }
    };

    // tree-kill spawns `ps` internally. If `ps` is missing from the image
    // (procps not installed), the spawn emits an 'error' event that tree-kill
    // does NOT catch — it propagates as an uncaughtException and crashes the
    // whole node process. Guard against that by installing a one-shot
    // uncaughtException handler around the call, plus the callback fallback.
    const onUncaught = (err: Error) => {
      const msg = err.message ?? "";
      if (msg.includes("spawn ps") || msg.includes("ENOENT")) {
        logError("tree-kill spawn-ps crash intercepted — using fallback", err);
        fallbackDirectKill();
        resolve();
      } else {
        // Not ours — rethrow so other handlers (or the default) see it.
        process.removeListener("uncaughtException", onUncaught);
        throw err;
      }
    };
    process.once("uncaughtException", onUncaught);

    try {
      treeKill(pid, "SIGTERM", (err) => {
        process.removeListener("uncaughtException", onUncaught);
        if (err) {
          logError("tree-kill failed, falling back to direct kill", err);
          fallbackDirectKill();
        }
        resolve();
      });
    } catch (err) {
      process.removeListener("uncaughtException", onUncaught);
      logError("tree-kill threw synchronously, falling back to direct kill", err);
      fallbackDirectKill();
      resolve();
    }
  });
}

export async function withTimeout<T>(
  promise: Promise<T>,
  ms: number,
  label: string
): Promise<T> {
  let timer: NodeJS.Timeout | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} timed out after ${ms}ms`)), ms);
  });
  try {
    return await Promise.race([promise, timeout]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

export interface StageError extends Error {
  stage: string;
  cause?: unknown;
}

// Tag an error with which pipeline stage it came from so PR comments can be
// specific ("build failed" vs "screenshot failed"). Mirrors how GodComet's
// workflow_executor surfaces stage names.
export function stageError(stage: string, err: unknown): StageError {
  const msg = err instanceof Error ? err.message : String(err);
  const e = new Error(`[${stage}] ${msg}`) as StageError;
  e.stage = stage;
  e.cause = err;
  if (err instanceof Error && err.stack) e.stack = err.stack;
  return e;
}

export async function timed<T>(
  stage: string,
  fn: () => Promise<T>,
  collect?: { stage: string; ms: number }[]
): Promise<T> {
  const start = Date.now();
  try {
    const result = await fn();
    const ms = Date.now() - start;
    log(`[${stage}] done in ${ms}ms`);
    collect?.push({ stage, ms });
    return result;
  } catch (err) {
    const ms = Date.now() - start;
    logError(`[${stage}] failed after ${ms}ms`);
    collect?.push({ stage, ms });
    throw stageError(stage, err);
  }
}

// Exponential backoff retry. Defaults match production_figma_converter.py:
// base_wait * 2^attempt → 30s, 60s, 120s, 240s. Used for rate-limited / flaky
// remote operations (git clone, GitHub API).
export interface RetryOptions {
  maxAttempts?: number; // default 3
  baseDelayMs?: number; // default 30_000 (matches GodComet)
  shouldRetry?: (err: unknown, attempt: number) => boolean;
  label?: string;
}

export async function retryWithBackoff<T>(
  fn: () => Promise<T>,
  opts: RetryOptions = {}
): Promise<T> {
  const maxAttempts = opts.maxAttempts ?? 3;
  const baseDelayMs = opts.baseDelayMs ?? 30_000;
  const shouldRetry = opts.shouldRetry ?? (() => true);
  const label = opts.label ?? "operation";
  let lastErr: unknown;
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    try {
      return await fn();
    } catch (err) {
      lastErr = err;
      const isLast = attempt === maxAttempts - 1;
      if (isLast || !shouldRetry(err, attempt)) {
        throw err;
      }
      const wait = baseDelayMs * Math.pow(2, attempt);
      log(
        `[retry] ${label} attempt ${attempt + 1}/${maxAttempts} failed: ${
          err instanceof Error ? err.message : String(err)
        }. Waiting ${wait}ms before retry.`
      );
      await new Promise((r) => setTimeout(r, wait));
    }
  }
  throw lastErr;
}

// Heuristic: is this error a rate-limit / transient HTTP error worth retrying?
export function isRetriableHttpError(err: unknown): boolean {
  if (!err || typeof err !== "object") return false;
  const e = err as { status?: number; code?: string; message?: string };
  if (e.status === 429) return true;
  if (e.status && e.status >= 500 && e.status < 600) return true;
  // Node-style network errors don't have a status. Only read `.code` in that
  // case — octokit's RequestError has a deprecated `.code` alias for `.status`
  // and reading it emits a deprecation warning.
  if (e.status === undefined) {
    if (e.code === "ETIMEDOUT" || e.code === "ECONNRESET" || e.code === "ENOTFOUND") {
      return true;
    }
  }
  const msg = (e.message ?? "").toLowerCase();
  if (msg.includes("rate limit") || msg.includes("rate_limit")) return true;
  if (msg.includes("timeout") || msg.includes("timed out")) return true;
  return false;
}
