import { spawn, type ChildProcess } from "node:child_process";
import { cpSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { log, waitForServer, killProcess } from "./utils.js";
import {
  findStaticDir,
  serveStaticDir,
  NoServableOutputError,
} from "./static-server.js";

export interface RunningServer {
  process: ChildProcess;
  port: number;
}

interface PackageJson {
  scripts?: Record<string, string>;
}

function detectPackageManager(dir: string): "npm" | "yarn" | "pnpm" {
  if (existsSync(join(dir, "pnpm-lock.yaml"))) return "pnpm";
  if (existsSync(join(dir, "yarn.lock"))) return "yarn";
  return "npm";
}

function readScripts(dir: string): Record<string, string> {
  const pkgPath = join(dir, "package.json");
  if (!existsSync(pkgPath)) {
    throw new Error("No package.json found in repo root");
  }
  const pkg = JSON.parse(readFileSync(pkgPath, "utf-8")) as PackageJson;
  return pkg.scripts ?? {};
}

function runCommand(
  cmd: string,
  args: string[],
  cwd: string,
  env: NodeJS.ProcessEnv
): Promise<void> {
  return new Promise((resolve, reject) => {
    const proc = spawn(cmd, args, {
      cwd,
      env,
      shell: process.platform === "win32",
    });
    let stderr = "";
    proc.stdout.on("data", (d) => process.stdout.write(d));
    proc.stderr.on("data", (d) => {
      const s = d.toString();
      stderr += s;
      process.stderr.write(d);
    });
    proc.on("error", reject);
    proc.on("close", (code) => {
      if (code === 0) resolve();
      else
        reject(
          new Error(`${cmd} ${args.join(" ")} failed (exit ${code}):\n${stderr.slice(-2000)}`)
        );
    });
  });
}

function startServer(
  cmd: string,
  args: string[],
  cwd: string,
  env: NodeJS.ProcessEnv
): ChildProcess {
  const proc = spawn(cmd, args, {
    cwd,
    env,
    shell: process.platform === "win32",
    detached: process.platform !== "win32",
  });
  proc.stdout.on("data", (d) => process.stdout.write(d));
  proc.stderr.on("data", (d) => process.stderr.write(d));
  return proc;
}

interface BuildContext {
  pm: "npm" | "yarn" | "pnpm";
  scripts: Record<string, string>;
  env: NodeJS.ProcessEnv;
  installEnv: NodeJS.ProcessEnv;
  visualbotModules: string;
}

function prepareBuildContext(repoDir: string, port: number): BuildContext {
  const pm = detectPackageManager(repoDir);
  const scripts = readScripts(repoDir);
  const visualbotDir = dirname(fileURLToPath(import.meta.url));
  const visualbotModules = join(visualbotDir, "../node_modules");
  // NODE_PATH lets Turbopack's child processes resolve transitive deps
  // (e.g. @alloc/quick-lru) from the visualbot's own node_modules when they
  // are missing from the cloned project.
  const existingNodePath = process.env.NODE_PATH ?? "";
  const nodePath = existingNodePath ? `${visualbotModules}:${existingNodePath}` : visualbotModules;
  // NODE_ENV=production causes npm to skip devDependencies. The Railway
  // container sets it globally, so we must unset it for the install step or
  // packages like @types/react and @tailwindcss/postcss won't be installed.
  const installEnv: NodeJS.ProcessEnv = { ...process.env, CI: "1", NODE_ENV: "development", NODE_PATH: nodePath };
  const env: NodeJS.ProcessEnv = { ...process.env, PORT: String(port), CI: "1", NODE_PATH: nodePath };

  return { pm, scripts, env, installEnv, visualbotModules };
}

async function installDependencies(repoDir: string, ctx: BuildContext): Promise<void> {
  const { pm, installEnv, visualbotModules } = ctx;
  log(`[builder] using ${pm} in ${repoDir}`);

  const installArgs =
    pm === "npm" ? ["install", "--no-audit", "--no-fund"] : ["install"];
  await runCommand(pm, installArgs, repoDir, installEnv);

  // Copy @tailwindcss/postcss directly into the cloned project's node_modules
  // so it is resolvable from the project root. NODE_PATH alone is not enough
  // because postcss.config.js resolution starts from the project directory.
  // The copy covers the entry point; NODE_PATH covers its transitive deps.
  const destTailwindPostcss = join(repoDir, "node_modules", "@tailwindcss", "postcss");
  if (!existsSync(destTailwindPostcss)) {
    const srcTailwindPostcss = join(visualbotModules, "@tailwindcss", "postcss");
    if (existsSync(srcTailwindPostcss)) {
      log("[builder] @tailwindcss/postcss missing — copying from visualbot node_modules");
      mkdirSync(join(repoDir, "node_modules", "@tailwindcss"), { recursive: true });
      cpSync(srcTailwindPostcss, destTailwindPostcss, { recursive: true });
    }
  }
}

async function runBuildScript(repoDir: string, ctx: BuildContext): Promise<void> {
  if (ctx.scripts.build) {
    log(`[builder] running ${ctx.pm} run build`);
    await runCommand(ctx.pm, ["run", "build"], repoDir, ctx.env);
  } else {
    log("[builder] no build script — skipping");
  }
}

/**
 * Tier 4 — install, build, and boot the project's own server.
 *
 * Used when the repo has a `start` or `dev` script to run.
 */
export async function buildAndStart(
  repoDir: string,
  port: number
): Promise<RunningServer> {
  const ctx = prepareBuildContext(repoDir, port);
  log(`[builder] PORT=${port}`);

  await installDependencies(repoDir, ctx);
  await runBuildScript(repoDir, ctx);

  const { scripts, pm, env } = ctx;
  let startScript: string;
  let startArgs: string[];
  if (scripts.start) {
    startScript = "start";
    startArgs = ["run", "start"];
  } else if (scripts.dev) {
    startScript = "dev";
    startArgs = ["run", "dev"];
  } else {
    throw new Error("No 'start' or 'dev' script in package.json");
  }
  log(`[builder] launching ${pm} run ${startScript} on port ${port}`);

  const proc = startServer(pm, startArgs, repoDir, env);

  let exitedEarly: Error | null = null;
  proc.on("exit", (code, signal) => {
    if (code !== 0 && code !== null) {
      exitedEarly = new Error(
        `Dev server exited early with code ${code} signal ${signal}`
      );
    }
  });

  try {
    await waitForServer(port, 90_000);
  } catch (err) {
    await killProcess(proc);
    if (exitedEarly) throw exitedEarly;
    throw err;
  }

  log(`[builder] server ready on port ${port}`);
  return { process: proc, port };
}

/**
 * Tier 3 — install, build, then serve the emitted static directory.
 *
 * Used when the repo has a `build` script but nothing to `start`. Avoids
 * booting a dev server entirely: the build output is plain files, so a static
 * server is both sufficient and far more predictable.
 */
export async function buildAndServeStatic(
  repoDir: string,
  port: number
): Promise<RunningServer> {
  const ctx = prepareBuildContext(repoDir, port);
  log(`[builder] static-output mode, PORT=${port}`);

  await installDependencies(repoDir, ctx);
  await runBuildScript(repoDir, ctx);

  const staticDir = findStaticDir(repoDir);
  if (!staticDir) {
    throw new NoServableOutputError(
      "Build completed but no servable static output was found " +
        "(looked for dist/, build/, out/, _site/, public/ containing an index.html)"
    );
  }

  const proc = await serveStaticDir(staticDir, port);

  let exitedEarly: Error | null = null;
  proc.on("exit", (code, signal) => {
    if (code !== 0 && code !== null) {
      exitedEarly = new Error(
        `Static server exited early with code ${code} signal ${signal}`
      );
    }
  });

  try {
    // Static serving has no compile step, so it is ready almost immediately.
    await waitForServer(port, 30_000);
  } catch (err) {
    await killProcess(proc);
    if (exitedEarly) throw exitedEarly;
    throw err;
  }

  log(`[builder] static server ready on port ${port}`);
  return { process: proc, port };
}
