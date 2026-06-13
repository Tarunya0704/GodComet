import { spawn, type ChildProcess } from "node:child_process";
import { cpSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { log, waitForServer, killProcess } from "./utils.js";

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

export async function buildAndStart(
  repoDir: string,
  port: number
): Promise<RunningServer> {
  const pm = detectPackageManager(repoDir);
  const scripts = readScripts(repoDir);
  const env: NodeJS.ProcessEnv = { ...process.env, PORT: String(port), CI: "1" };

  log(`[builder] using ${pm} in ${repoDir}, PORT=${port}`);

  const installArgs =
    pm === "npm" ? ["install", "--no-audit", "--no-fund"] : ["install"];
  await runCommand(pm, installArgs, repoDir, env);

  // Turbopack resolves PostCSS plugins from the project root. If a project
  // uses @tailwindcss/postcss (Tailwind v4) but omits it from package.json,
  // npm won't install it and the build fails. npm install --no-save is
  // unreliable here because npm considers the package "up to date" when it
  // finds it nested inside another package's node_modules — but Turbopack
  // still can't find it. Copying directly from the visualbot's own
  // node_modules guarantees it lands at the right top-level path.
  const destTailwindPostcss = join(repoDir, "node_modules", "@tailwindcss", "postcss");
  if (!existsSync(destTailwindPostcss)) {
    const visualbotDir = dirname(fileURLToPath(import.meta.url));
    const srcTailwindPostcss = join(visualbotDir, "../node_modules/@tailwindcss/postcss");
    if (existsSync(srcTailwindPostcss)) {
      log("[builder] @tailwindcss/postcss missing — copying from visualbot node_modules");
      mkdirSync(join(repoDir, "node_modules", "@tailwindcss"), { recursive: true });
      cpSync(srcTailwindPostcss, destTailwindPostcss, { recursive: true });
    }
  }

  if (scripts.build) {
    log(`[builder] running ${pm} run build`);
    await runCommand(pm, ["run", "build"], repoDir, env);
  } else {
    log("[builder] no build script — skipping");
  }

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
