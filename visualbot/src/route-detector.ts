// Auto-detects which routes to screenshot based on the files changed in a PR.
//
// Strategy:
//   1. Detect the JS framework from package.json (Next.js, Remix, SvelteKit, Nuxt).
//   2. Classify every changed file as one of:
//        route    — maps directly to a screenshottable URL
//        dynamic  — has a param segment ([slug], $id) — can't screenshot, skip + log
//        global   — affects all pages (shared component, global CSS, layout, config)
//        ignore   — API route, config file, test, etc.
//   3. Collect unique routes from "route" files.
//      If any "global" file changed, always include "/" (global changes affect the homepage).
//   4. Cap at MAX_AUTO_ROUTES so a huge PR doesn't spawn 50 screenshot jobs.
//
// Callers should prefer .shirodiff.yml when it exists — this runs only when
// no manual config is present.

import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { log } from "./utils.js";

export interface DetectionResult {
  routes: string[];
  skippedDynamic: string[];
  hadGlobalChanges: boolean;
  framework: string;
}

type Framework = "nextjs-app" | "nextjs-pages" | "remix" | "sveltekit" | "nuxt" | "unknown";

type FileClassification =
  | { type: "route"; route: string }
  | { type: "dynamic"; route: string }
  | { type: "global" }
  | { type: "ignore" };

const MAX_AUTO_ROUTES = 10;

// ─── framework detection ─────────────────────────────────────────────────────

function detectFramework(repoDir: string): Framework {
  let deps: Record<string, string> = {};
  try {
    const pkg = JSON.parse(readFileSync(join(repoDir, "package.json"), "utf-8")) as {
      dependencies?: Record<string, string>;
      devDependencies?: Record<string, string>;
    };
    deps = { ...(pkg.dependencies ?? {}), ...(pkg.devDependencies ?? {}) };
  } catch {
    /* no package.json or parse error */
  }

  if (deps["@sveltejs/kit"]) return "sveltekit";
  if (
    deps["@remix-run/react"] ||
    deps["@remix-run/node"] ||
    deps["@remix-run/server-runtime"]
  ) return "remix";
  if (deps["nuxt"]) return "nuxt";
  if (deps["next"]) {
    // App Router projects have an app/ directory alongside (or instead of) pages/.
    return existsSync(join(repoDir, "app")) ? "nextjs-app" : "nextjs-pages";
  }
  return "unknown";
}

// ─── helpers ─────────────────────────────────────────────────────────────────

function stripExt(s: string): string {
  return s.replace(/\.(tsx?|jsx?|svelte|vue|mdx?)$/, "");
}

// A path segment is dynamic if it holds a runtime parameter.
function isDynamicSegment(seg: string): boolean {
  return (
    (seg.startsWith("[") && seg.endsWith("]")) || // Next.js [param] / [[...param]]
    seg.startsWith("$") ||                         // Remix $param
    seg.startsWith(":") ||                         // plain URL param notation
    seg === "..."
  );
}

// Route groups like (marketing) are organisational — they don't appear in URLs.
function isRouteGroup(seg: string): boolean {
  return seg.startsWith("(") && seg.endsWith(")");
}

// ─── framework-agnostic global patterns ──────────────────────────────────────

const GLOBAL_PREFIXES = [
  "components/", "src/components/",
  "styles/",     "src/styles/",
  "hooks/",      "src/hooks/",
  "lib/",        "src/lib/",
  "utils/",      "src/utils/",
  "context/",    "src/context/",
  "store/",      "src/store/",
  "providers/",  "src/providers/",
  "layouts/",    "src/layouts/",
  "public/",
];

const GLOBAL_EXACT = new Set([
  "tailwind.config.js",  "tailwind.config.ts",  "tailwind.config.cjs", "tailwind.config.mjs",
  "postcss.config.js",   "postcss.config.ts",   "postcss.config.cjs",
  "next.config.js",      "next.config.ts",       "next.config.mjs",
  "vite.config.js",      "vite.config.ts",
  "nuxt.config.js",      "nuxt.config.ts",
  "svelte.config.js",    "svelte.config.ts",
  "remix.config.js",     "remix.config.ts",
  "src/app.css",         "src/app.html",         "src/app.pcss",
]);

function isAlwaysGlobal(file: string): boolean {
  if (GLOBAL_EXACT.has(file)) return true;
  if (GLOBAL_PREFIXES.some(p => file.startsWith(p))) return true;
  // Any stylesheet regardless of location
  if (/\.(css|scss|less|sass|pcss)$/.test(file)) return true;
  return false;
}

// ─── per-framework classifiers ────────────────────────────────────────────────

function classifyNextjsPages(file: string): FileClassification {
  if (!file.startsWith("pages/")) return { type: "ignore" };
  const rel = file.slice("pages/".length);
  if (rel.startsWith("api/")) return { type: "ignore" };
  if (/^_app\.|^_document\.|^_error\./.test(rel)) return { type: "global" };

  const clean = stripExt(rel)
    .replace(/\/index$/, "")
    .replace(/^index$/, "");
  const segments = clean ? clean.split("/") : [];

  if (segments.some(isDynamicSegment)) {
    return { type: "dynamic", route: "/" + segments.join("/") };
  }
  return { type: "route", route: segments.length ? "/" + segments.join("/") : "/" };
}

function classifyNextjsApp(file: string): FileClassification {
  if (!file.startsWith("app/")) return { type: "ignore" };
  const rel = file.slice("app/".length);
  const parts = rel.split("/");
  const filename = parts[parts.length - 1];

  // API routes
  if (rel.startsWith("api/") || filename.startsWith("route.")) return { type: "ignore" };

  // Layout, loading, error, and root-level files are global
  if (
    filename.startsWith("layout.") ||
    filename.startsWith("template.") ||
    filename.startsWith("error.") ||
    filename.startsWith("loading.") ||
    filename.startsWith("not-found.") ||
    parts.length === 1
  ) return { type: "global" };

  // Only page.* files map to routes
  if (!filename.startsWith("page.")) return { type: "ignore" };

  const dirParts = parts.slice(0, -1).filter(s => !isRouteGroup(s));
  if (dirParts.some(isDynamicSegment)) {
    return { type: "dynamic", route: "/" + dirParts.join("/") };
  }
  return { type: "route", route: dirParts.length ? "/" + dirParts.join("/") : "/" };
}

function classifyRemix(file: string): FileClassification {
  // Root shell affects everything
  if (/^app\/root\.(tsx?|jsx?)$/.test(file)) return { type: "global" };
  if (!file.startsWith("app/routes/")) return { type: "ignore" };

  const withoutExt = stripExt(file.slice("app/routes/".length));

  // Root index
  if (withoutExt === "_index") return { type: "route", route: "/" };

  // Remix v2 flat routes: dots are path separators.
  // Layout prefixes start with _ — strip them.
  // _index suffix is the index route — also strip it.
  const segments = withoutExt
    .split(".")
    .filter(s => s !== "_index")
    .filter(s => !s.startsWith("_"));

  if (segments.some(s => s.startsWith("$"))) {
    return { type: "dynamic", route: "/" + segments.join("/") };
  }
  return { type: "route", route: segments.length ? "/" + segments.join("/") : "/" };
}

function classifySvelteKit(file: string): FileClassification {
  if (!file.startsWith("src/routes/")) return { type: "ignore" };
  const rel = file.slice("src/routes/".length);
  const parts = rel.split("/");
  const filename = parts[parts.length - 1];

  // Layout and error files affect all routes at or below their level
  if (filename.startsWith("+layout.") || filename.startsWith("+error.")) {
    return { type: "global" };
  }

  // Only +page files map to screenshottable routes
  if (!filename.startsWith("+page.")) return { type: "ignore" };

  const dirParts = parts.slice(0, -1).filter(s => !isRouteGroup(s));
  if (dirParts.some(s => s.startsWith("[") || s.startsWith("..."))) {
    return { type: "dynamic", route: "/" + dirParts.join("/") };
  }
  return { type: "route", route: dirParts.length ? "/" + dirParts.join("/") : "/" };
}

function classifyNuxt(file: string): FileClassification {
  if (!file.startsWith("pages/")) return { type: "ignore" };
  if (!file.endsWith(".vue")) return { type: "ignore" };

  const clean = stripExt(file.slice("pages/".length))
    .replace(/\/index$/, "")
    .replace(/^index$/, "");
  const segments = clean ? clean.split("/") : [];

  // Nuxt uses [param] for dynamic segments (v3) and _param (v2)
  if (segments.some(s => s.startsWith("[") || s.startsWith("_"))) {
    return { type: "dynamic", route: "/" + segments.join("/") };
  }
  return { type: "route", route: segments.length ? "/" + segments.join("/") : "/" };
}

function classifyFile(file: string, framework: Framework): FileClassification {
  if (isAlwaysGlobal(file)) return { type: "global" };

  switch (framework) {
    case "nextjs-pages": return classifyNextjsPages(file);
    case "nextjs-app":   return classifyNextjsApp(file);
    case "remix":        return classifyRemix(file);
    case "sveltekit":    return classifySvelteKit(file);
    case "nuxt":         return classifyNuxt(file);
    default: {
      // Unknown framework: try both Next.js conventions as best-effort heuristics.
      const p = classifyNextjsPages(file);
      if (p.type !== "ignore") return p;
      const a = classifyNextjsApp(file);
      if (a.type !== "ignore") return a;
      return { type: "ignore" };
    }
  }
}

// ─── main export ─────────────────────────────────────────────────────────────

export function detectRoutes(
  changedFiles: string[],
  repoDir: string
): DetectionResult {
  const framework = detectFramework(repoDir);
  log(`[route-detector] framework=${framework}, ${changedFiles.length} changed file(s)`);

  const routes = new Set<string>();
  const skippedDynamic: string[] = [];
  let hadGlobalChanges = false;

  for (const file of changedFiles) {
    const cls = classifyFile(file, framework);
    switch (cls.type) {
      case "route":
        routes.add(cls.route);
        break;
      case "dynamic":
        if (!skippedDynamic.includes(cls.route)) skippedDynamic.push(cls.route);
        break;
      case "global":
        hadGlobalChanges = true;
        break;
      // "ignore" → silent
    }
  }

  // Global changes always need / — even if no direct page file changed,
  // a shared component or CSS edit could visually break the homepage.
  if (hadGlobalChanges) routes.add("/");

  const finalRoutes = [...routes].slice(0, MAX_AUTO_ROUTES);

  if (finalRoutes.length === 0) {
    log(`[route-detector] no routes detected — falling back to /`);
    return { routes: ["/"], skippedDynamic, hadGlobalChanges, framework };
  }

  log(
    `[route-detector] routes: ${finalRoutes.join(", ")}` +
    (skippedDynamic.length ? ` | skipped dynamic: ${skippedDynamic.join(", ")}` : "")
  );

  return { routes: finalRoutes, skippedDynamic, hadGlobalChanges, framework };
}
