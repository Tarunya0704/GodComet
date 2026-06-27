import { readFileSync } from "node:fs";
import { join } from "node:path";
import yaml from "js-yaml";
import { log } from "./utils.js";

export interface ShiroDiffConfig {
  routes: string[];
}

const DEFAULT_CONFIG: ShiroDiffConfig = { routes: ["/"] };
const MAX_ROUTES = 20;

// Reads .shirodiff.yml from the root of the cloned repo directory.
// Always returns a valid config — falls back to { routes: ["/"] } on any
// error (missing file, bad YAML, wrong schema) so the existing single-page
// behavior is fully preserved for repos that don't have the file.
export function readConfig(repoDir: string): ShiroDiffConfig {
  const configPath = join(repoDir, ".shirodiff.yml");
  let raw: string;
  try {
    raw = readFileSync(configPath, "utf-8");
  } catch {
    return DEFAULT_CONFIG;
  }

  try {
    const parsed = yaml.load(raw) as unknown;
    if (
      !parsed ||
      typeof parsed !== "object" ||
      !("routes" in parsed)
    ) {
      log("[config] .shirodiff.yml missing 'routes' key — using default [/]");
      return DEFAULT_CONFIG;
    }
    const routes = (parsed as { routes: unknown }).routes;
    if (!Array.isArray(routes)) {
      log("[config] .shirodiff.yml 'routes' is not an array — using default [/]");
      return DEFAULT_CONFIG;
    }
    const validRoutes = routes
      .filter((r): r is string => typeof r === "string" && r.startsWith("/"))
      .slice(0, MAX_ROUTES);
    if (validRoutes.length === 0) {
      log("[config] .shirodiff.yml has no valid routes — using default [/]");
      return DEFAULT_CONFIG;
    }
    log(`[config] loaded ${validRoutes.length} route(s): ${validRoutes.join(", ")}`);
    return { routes: validRoutes };
  } catch (err) {
    log(
      `[config] failed to parse .shirodiff.yml: ${(err as Error).message} — using default [/]`
    );
    return DEFAULT_CONFIG;
  }
}
