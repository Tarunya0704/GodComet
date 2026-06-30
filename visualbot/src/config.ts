import { readFileSync } from "node:fs";
import { join } from "node:path";
import yaml from "js-yaml";
import { log } from "./utils.js";

export interface ShiroDiffConfig {
  routes: string[];
}

const DEFAULT_CONFIG: ShiroDiffConfig = { routes: ["/"] };
const MAX_ROUTES = 20;

// Reads .shirodiff.yml from the root of the cloned repo.
//
// Returns null  → file doesn't exist; caller should use auto-detection.
// Returns config → file exists (caller respects it even if it defaulted due to
//                  bad YAML, because the presence of the file signals intent).
export function readConfig(repoDir: string): ShiroDiffConfig | null {
  const configPath = join(repoDir, ".shirodiff.yml");
  let raw: string;
  try {
    raw = readFileSync(configPath, "utf-8");
  } catch {
    return null;
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
