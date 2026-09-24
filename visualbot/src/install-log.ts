// Installation lifecycle logging.
//
// `installations_count` from the GitHub API is a live gauge, not a total: an
// uninstall erases the install with no trace, so churn is invisible after the
// fact. GitHub's own webhook delivery log retains only a few days. This writes
// the events down as they arrive so growth and churn stay answerable later.
//
// Append-only JSONL, one object per line. No database, no rotation.

import { appendFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { logError } from "./utils.js";

const DEFAULT_LOG_PATH = "/tmp/shirodiff-installs.log";

export function installLogPath(): string {
  return process.env.INSTALL_LOG_PATH || DEFAULT_LOG_PATH;
}

/** ISO-8601 to whole seconds — `2026-09-25T10:30:00Z`. */
function timestamp(): string {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/**
 * `installation.account` is a union (user/org vs. enterprise) whose branches
 * don't share fields — enterprises carry `slug`/`name` and no `type`. Read it
 * structurally so an unexpected shape degrades to "unknown" instead of
 * throwing inside a webhook handler.
 */
function readAccount(account: unknown): { login: string; type: string } {
  const a = (account ?? {}) as {
    login?: string;
    slug?: string;
    name?: string;
    type?: string;
  };
  return {
    login: a.login ?? a.slug ?? a.name ?? "unknown",
    type: a.type ?? "Unknown",
  };
}

function readRepoNames(repos: unknown): string[] {
  if (!Array.isArray(repos)) return [];
  return repos
    .map((r) => (r as { name?: string })?.name)
    .filter((n): n is string => typeof n === "string");
}

/**
 * Append one record. Never throws.
 *
 * A webhook handler that throws makes Probot return 500, which makes GitHub
 * retry the delivery — so a full disk or a bad INSTALL_LOG_PATH would turn
 * into duplicated records. Telemetry must not be able to do that.
 */
function appendRecord(record: Record<string, unknown>): void {
  const path = installLogPath();
  try {
    mkdirSync(dirname(path), { recursive: true });
    appendFileSync(path, JSON.stringify(record) + "\n", "utf-8");
  } catch (err) {
    logError(`[install-log] failed to write ${path}:`, err);
  }
}

interface InstallationPayload {
  installation?: {
    id?: number;
    account?: unknown;
  };
  repositories?: unknown;
  repositories_added?: unknown;
  repositories_removed?: unknown;
}

export function recordInstall(payload: InstallationPayload): void {
  const { login, type } = readAccount(payload.installation?.account);
  const id = payload.installation?.id ?? 0;
  const repos = readRepoNames(payload.repositories).length;
  const ts = timestamp();

  console.log(
    `[INSTALL] @${login} installed on ${plural(repos, "repo")} at ${ts} (id: ${id})`
  );
  appendRecord({
    event: "install",
    account: login,
    account_type: type,
    repos,
    timestamp: ts,
    installation_id: id,
  });
}

export function recordUninstall(payload: InstallationPayload): void {
  const { login, type } = readAccount(payload.installation?.account);
  const id = payload.installation?.id ?? 0;
  const ts = timestamp();

  console.log(`[UNINSTALL] @${login} uninstalled at ${ts} (id: ${id})`);
  appendRecord({
    event: "uninstall",
    account: login,
    account_type: type,
    timestamp: ts,
    installation_id: id,
  });
}

export function recordReposAdded(payload: InstallationPayload): void {
  const { login } = readAccount(payload.installation?.account);
  const id = payload.installation?.id ?? 0;
  const names = readRepoNames(payload.repositories_added);
  const ts = timestamp();

  console.log(
    `[REPOS_ADDED] @${login} added ${plural(names.length, "repo")} at ${ts} (id: ${id})`
  );
  appendRecord({
    event: "repos_added",
    account: login,
    repos_added: names,
    timestamp: ts,
    installation_id: id,
  });
}

export function recordReposRemoved(payload: InstallationPayload): void {
  const { login } = readAccount(payload.installation?.account);
  const id = payload.installation?.id ?? 0;
  const names = readRepoNames(payload.repositories_removed);
  const ts = timestamp();

  console.log(
    `[REPOS_REMOVED] @${login} removed ${plural(names.length, "repo")} at ${ts} (id: ${id})`
  );
  appendRecord({
    event: "repos_removed",
    account: login,
    repos_removed: names,
    timestamp: ts,
    installation_id: id,
  });
}
