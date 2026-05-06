// Git clone — patterns ported from mcp-automation/src/tools/github_tool.py.
//
// Lessons applied:
//   - Explicit user.email / user.name config (github_tool.py:140-145) so any
//     write op (e.g. our orphan asset branch) doesn't fail with "please tell
//     me who you are" on a fresh container.
//   - Retry on transient failures (github_tool.py:215-228 retry-then-force);
//     we adapt this to clone: retry transient network errors with exponential
//     backoff, but only for *retriable* errors (404 = bad SHA, do not retry).
//   - Specific timeouts on each git command (github_tool.py:71-92 _run_git_command).
//   - Surface stderr in the error message so the PR comment can show the
//     actual git error (e.g. "Repository not found").

import { spawn } from "node:child_process";
import { log } from "./utils.js";
import { retryWithBackoff } from "./utils.js";

interface CloneOptions {
  owner: string;
  repo: string;
  sha: string;
  installationToken: string;
  targetDir: string;
}

interface RunResult {
  stdout: string;
  stderr: string;
}

class GitCommandError extends Error {
  exitCode: number;
  stderr: string;
  fatal: boolean;
  constructor(message: string, exitCode: number, stderr: string, fatal: boolean) {
    super(message);
    this.exitCode = exitCode;
    this.stderr = stderr;
    this.fatal = fatal;
  }
}

function classifyGitError(stderr: string, exitCode: number): { fatal: boolean } {
  // github_tool.py uses a "fatal" flag to skip retries on permanent failures.
  // We mirror that here: bad SHAs / auth failures should NOT be retried.
  const lower = stderr.toLowerCase();
  if (lower.includes("repository not found")) return { fatal: true };
  if (lower.includes("authentication failed")) return { fatal: true };
  if (lower.includes("could not read username")) return { fatal: true };
  if (lower.includes("did not match any") || lower.includes("couldn't find remote ref")) {
    // bad SHA — fatal, no retry.
    return { fatal: true };
  }
  // Network/transient errors → retry.
  if (
    lower.includes("could not resolve host") ||
    lower.includes("connection reset") ||
    lower.includes("connection timed out") ||
    lower.includes("operation timed out") ||
    lower.includes("rpc failed") ||
    lower.includes("early eof") ||
    lower.includes("the remote end hung up")
  ) {
    return { fatal: false };
  }
  // Default: treat unknown failures as fatal so we don't waste 4 minutes
  // on retries for a real bug.
  return { fatal: exitCode === 0 ? false : true };
}

function run(
  cmd: string,
  args: string[],
  cwd: string,
  timeoutMs = 300_000
): Promise<RunResult> {
  // Patterned on github_tool.py:71-92 _run_git_command — explicit timeout,
  // captured stdout/stderr, exit-code check.
  return new Promise((resolve, reject) => {
    const proc = spawn(cmd, args, { cwd, shell: false });
    let stdout = "";
    let stderr = "";
    let timer: NodeJS.Timeout | null = null;

    if (timeoutMs > 0) {
      timer = setTimeout(() => {
        try {
          proc.kill("SIGKILL");
        } catch {
          // ignore
        }
        reject(
          new GitCommandError(
            `${cmd} ${args.join(" ")} timed out after ${timeoutMs}ms`,
            -1,
            stderr,
            true
          )
        );
      }, timeoutMs);
    }

    proc.stdout.on("data", (d) => (stdout += d.toString()));
    proc.stderr.on("data", (d) => (stderr += d.toString()));
    proc.on("error", (err) => {
      if (timer) clearTimeout(timer);
      reject(err);
    });
    proc.on("close", (code) => {
      if (timer) clearTimeout(timer);
      if (code === 0) {
        resolve({ stdout, stderr });
      } else {
        const { fatal } = classifyGitError(stderr, code ?? -1);
        reject(
          new GitCommandError(
            `${cmd} ${args.join(" ")} exited ${code}: ${stderr.slice(-1000)}`,
            code ?? -1,
            stderr,
            fatal
          )
        );
      }
    });
  });
}

async function configureGitAuthor(targetDir: string): Promise<void> {
  // Mirrors github_tool.py:140-145. Needed because our orphan-branch asset
  // upload calls git via the REST API — but if anyone reuses this clone for
  // local commits, this avoids the "please tell me who you are" failure.
  await run(
    "git",
    ["config", "user.email", "visualbot[bot]@users.noreply.github.com"],
    targetDir,
    10_000
  );
  await run(
    "git",
    ["config", "user.name", "VisualBot"],
    targetDir,
    10_000
  );
}

async function cloneOnce(opts: CloneOptions): Promise<string> {
  const { owner, repo, sha, installationToken, targetDir } = opts;
  // Installation token works for both public and private repos (it's scoped to
  // the App's installation on the repo). The x-access-token user is the
  // documented format from GitHub Docs.
  const url = `https://x-access-token:${installationToken}@github.com/${owner}/${repo}.git`;

  log(`Cloning ${owner}/${repo} @ ${sha.slice(0, 7)} -> ${targetDir}`);

  await run("git", ["init", "--quiet"], targetDir, 15_000);
  await configureGitAuthor(targetDir);
  await run("git", ["remote", "add", "origin", url], targetDir, 15_000);
  await run(
    "git",
    ["fetch", "--depth", "1", "origin", sha],
    targetDir,
    240_000
  );
  await run("git", ["checkout", "--quiet", sha], targetDir, 60_000);

  log(`Cloned ${owner}/${repo} @ ${sha.slice(0, 7)}`);
  return targetDir;
}

export async function cloneAtSha(opts: CloneOptions): Promise<string> {
  // Retry only the *clone attempt* on transient network failures, not on
  // bad-SHA / auth errors. Backoff base of 5s — these are local clones, much
  // shorter than the 30s base used for GitHub API rate limits.
  return retryWithBackoff(() => cloneOnce(opts), {
    maxAttempts: 3,
    baseDelayMs: 5_000,
    label: `clone ${opts.owner}/${opts.repo}@${opts.sha.slice(0, 7)}`,
    shouldRetry: (err) => {
      if (err instanceof GitCommandError) return !err.fatal;
      return true;
    },
  });
}
