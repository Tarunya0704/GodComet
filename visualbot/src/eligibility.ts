// Pre-flight eligibility check.
//
// shiroDiff gets installed account-wide as often as repo-by-repo, so it lands
// on SQL, R, Python and plain-library repos it can never serve. Cloning those
// and letting `npm install` blow up produces a red ❌ comment on a PR that was
// never in scope — which reads as "this bot is broken" rather than "this bot
// isn't for this repo".
//
// So: one Contents API call before we touch git or post anything. If the repo
// doesn't look like something we can boot and screenshot, we log and leave.
// Silence is the feature.

import type { Context } from "probot";
import { log } from "./utils.js";

export interface EligibilityResult {
  eligible: boolean;
  reason: string;
  framework?: string;
  /** build script present, but nothing to `start` — Tier 3 static-output path. */
  hasStaticBuild?: boolean;
}

interface PackageJson {
  dependencies?: Record<string, string>;
  devDependencies?: Record<string, string>;
  scripts?: Record<string, string>;
}

// Dependency → display name. Ordered: the first match wins, so more specific
// meta-frameworks are listed before the bundlers/libraries they build on
// (a Next.js app that also has `vite` in devDeps should report as Next.js).
const FRAMEWORK_DEPS: ReadonlyArray<readonly [string, string]> = [
  ["next", "Next.js"],
  ["@remix-run/react", "Remix"],
  ["nuxt", "Nuxt"],
  ["@sveltejs/kit", "SvelteKit"],
  ["gatsby", "Gatsby"],
  ["@angular/core", "Angular"],
  ["vite", "Vite"],
  ["vue", "Vue"],
];

function detectFrameworkDep(pkg: PackageJson): string | undefined {
  const deps = { ...(pkg.dependencies ?? {}), ...(pkg.devDependencies ?? {}) };
  for (const [dep, name] of FRAMEWORK_DEPS) {
    if (deps[dep]) return name;
  }
  return undefined;
}

function classify(pkg: PackageJson): EligibilityResult {
  const scripts = pkg.scripts ?? {};
  const hasStart = typeof scripts.start === "string" && scripts.start.trim() !== "";
  const hasDev = typeof scripts.dev === "string" && scripts.dev.trim() !== "";
  const hasBuild = typeof scripts.build === "string" && scripts.build.trim() !== "";

  // A build script with nothing to start means the output is static — Tier 3
  // serves the built directory instead of booting a dev server.
  const hasStaticBuild = hasBuild && !hasStart && !hasDev;

  const framework = detectFrameworkDep(pkg);
  if (framework) {
    return {
      eligible: true,
      reason: `detected ${framework}`,
      framework,
      hasStaticBuild,
    };
  }

  if (hasStart || hasDev) {
    return {
      eligible: true,
      reason: `no known framework, but a '${hasStart ? "start" : "dev"}' script is present`,
      hasStaticBuild: false,
    };
  }

  if (hasBuild) {
    return {
      eligible: true,
      reason: "no start/dev script, but a 'build' script may produce static output",
      hasStaticBuild: true,
    };
  }

  return {
    eligible: false,
    reason: "no web framework or start/dev script detected",
  };
}

function decodeContent(data: unknown): PackageJson | null {
  // getContent returns an array for directories and a handful of non-file
  // shapes (symlink, submodule). Only a real file is useful here.
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;
  const file = data as { type?: string; content?: string; encoding?: string };
  if (file.type !== "file" || typeof file.content !== "string") return null;

  const raw =
    file.encoding === "base64"
      ? Buffer.from(file.content, "base64").toString("utf-8")
      : file.content;

  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
    return parsed as PackageJson;
  } catch {
    return null;
  }
}

export async function checkEligibility(
  context: Context<"pull_request">,
  owner: string,
  repo: string,
  ref: string
): Promise<EligibilityResult> {
  let data: unknown;
  try {
    const res = await context.octokit.repos.getContent({
      owner,
      repo,
      path: "package.json",
      ref,
    });
    data = res.data;
  } catch (err) {
    const status = (err as { status?: number }).status;

    // No package.json — Python, Go, Rust, SQL, a docs repo. Not ours.
    if (status === 404) {
      return { eligible: false, reason: "no package.json in repo root" };
    }

    // We can't read the repo. Whatever the cause, commenting about it would be
    // noise aimed at someone who can't act on it from the PR.
    if (status === 403 || status === 401) {
      return {
        eligible: false,
        reason: `cannot read package.json (HTTP ${status})`,
      };
    }

    // Anything else (5xx, socket hang-up, rate limit) is a problem with *us*,
    // not a verdict about the repo. Proceed and let the pipeline fail loudly
    // with a real error rather than silently dropping a PR we should have run.
    const msg = err instanceof Error ? err.message : String(err);
    return {
      eligible: true,
      reason: `eligibility check failed (${msg}) — proceeding on benefit of the doubt`,
    };
  }

  const pkg = decodeContent(data);
  if (!pkg) {
    // Present but unusable: unparseable JSON, a directory, an oversized file
    // returned without inline content. `npm install` would fail on all of
    // these, so a red comment adds nothing.
    return { eligible: false, reason: "package.json present but not readable as JSON" };
  }

  return classify(pkg);
}

/** Single place that decides how an eligibility verdict is logged. */
export function logEligibility(
  owner: string,
  repo: string,
  result: EligibilityResult
): void {
  if (!result.eligible) {
    log(`[eligibility] ${owner}/${repo} — skipping: ${result.reason}`);
    return;
  }
  const mode = result.hasStaticBuild ? "static-output" : "dev-server";
  log(`[eligibility] ${owner}/${repo} — eligible (${result.reason}) · mode=${mode}`);
}
