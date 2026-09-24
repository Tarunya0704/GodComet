// Tier 3 — serve a built static directory.
//
// A large share of the web repos shiroDiff sees don't need a dev server at
// all: the build step emits plain files and any static host would do. Serving
// those directly avoids the whole fragile business of booting someone else's
// dev server — no HMR websockets, no PORT-convention guessing, no process
// tree to hunt down afterwards.
//
// One static server covers Vite, CRA, Gatsby, Astro, Docusaurus, Hugo,
// Jekyll, Eleventy and hand-written HTML, in ~1 code path.

import { spawn, type ChildProcess } from "node:child_process";
import { existsSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { log } from "./utils.js";

/**
 * The build ran fine but emitted nothing a browser can open.
 *
 * This is an eligibility verdict we could only reach after building — a
 * TypeScript library's `tsc` fills dist/ with .js, never an index.html. It is
 * not a failure of the PR or of the bot, so it must never become a ❌ comment.
 */
export class NoServableOutputError extends Error {
  readonly silent = true as const;
  constructor(message: string) {
    super(message);
    this.name = "NoServableOutputError";
  }
}

/**
 * Is this error (or anything it wraps) a silent skip?
 *
 * `timed()` re-wraps failures via `stageError()`, which builds a *new* Error
 * and hangs the original off `.cause`. A bare `instanceof` at the catch site
 * would therefore never match, so walk the chain.
 */
export function isSilentSkip(err: unknown): boolean {
  let cur: unknown = err;
  for (let depth = 0; cur && depth < 10; depth++) {
    if (cur instanceof NoServableOutputError) return true;
    if (typeof cur === "object" && (cur as { silent?: unknown }).silent === true) {
      return true;
    }
    cur = (cur as { cause?: unknown }).cause;
  }
  return false;
}

// Priority order. First directory that looks like a servable site root wins.
const STATIC_OUTPUT_DIRS = ["dist", "build", "out", "_site", "public"] as const;

const NEXT_CONFIG_FILES = [
  "next.config.js",
  "next.config.ts",
  "next.config.mjs",
  "next.config.cjs",
];

function hasIndexHtml(dir: string): boolean {
  return existsSync(join(dir, "index.html")) || existsSync(join(dir, "index.htm"));
}

function isServableDir(dir: string): boolean {
  try {
    if (!statSync(dir).isDirectory()) return false;
  } catch {
    return false;
  }
  // index.html is the test for "site root", not merely "directory that exists".
  // Without it there is nothing for Playwright to open at `/`.
  return hasIndexHtml(dir);
}

/**
 * True when next.config declares `output: 'export'`.
 *
 * Note this only *confirms* a static export — it doesn't change where we look.
 * Next writes its export to `out/`, which is already in STATIC_OUTPUT_DIRS.
 * `.next/` itself is a build cache (server chunks, manifests) with no
 * index.html at its root, so it is deliberately never served.
 */
export function isNextStaticExport(repoDir: string): boolean {
  for (const name of NEXT_CONFIG_FILES) {
    const p = join(repoDir, name);
    if (!existsSync(p)) continue;
    try {
      const src = readFileSync(p, "utf-8");
      if (/output\s*:\s*['"`]export['"`]/.test(src)) return true;
    } catch {
      /* unreadable config — fall through */
    }
  }
  return false;
}

/** Locate the built site root, or null if the build produced nothing servable. */
export function findStaticDir(repoDir: string): string | null {
  for (const name of STATIC_OUTPUT_DIRS) {
    const candidate = join(repoDir, name);
    if (isServableDir(candidate)) {
      log(`[static] found static output in ${name}/`);
      return candidate;
    }
  }
  return null;
}

// The child server, as source. Runs via `node -e`, so it must be CommonJS and
// self-contained — no imports from this project, no build step, no temp file.
// Config arrives via env so nothing needs quoting.
//
// Kept free of backticks and template placeholders so it can live inside a TS
// template literal untouched.
const CHILD_SERVER_SRC = `
const http = require('http');
const fs = require('fs');
const path = require('path');

const root = process.env.SHIRODIFF_STATIC_ROOT;
const port = Number(process.env.SHIRODIFF_STATIC_PORT);

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.htm':  'text/html; charset=utf-8',
  '.css':  'text/css; charset=utf-8',
  '.js':   'text/javascript; charset=utf-8',
  '.mjs':  'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg':  'image/svg+xml',
  '.png':  'image/png',
  '.jpg':  'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif':  'image/gif',
  '.webp': 'image/webp',
  '.avif': 'image/avif',
  '.ico':  'image/x-icon',
  '.woff': 'font/woff',
  '.woff2':'font/woff2',
  '.ttf':  'font/ttf',
  '.otf':  'font/otf',
  '.eot':  'application/vnd.ms-fontobject',
  '.wasm': 'application/wasm',
  '.txt':  'text/plain; charset=utf-8',
  '.xml':  'application/xml; charset=utf-8',
  '.map':  'application/json; charset=utf-8',
  '.mp4':  'video/mp4',
  '.webm': 'video/webm'
};

function resolveFile(urlPath) {
  var target = path.join(root, urlPath);

  // Containment check: reject anything that escapes the served root.
  var rel = path.relative(root, target);
  if (rel.startsWith('..') || path.isAbsolute(rel)) return null;

  var st = null;
  try { st = fs.statSync(target); } catch (e) { st = null; }

  if (st && st.isDirectory()) {
    var idx = path.join(target, 'index.html');
    if (fs.existsSync(idx)) return idx;
    var idxm = path.join(target, 'index.htm');
    if (fs.existsSync(idxm)) return idxm;
    return null;
  }

  if (st && st.isFile()) return target;

  // Extensionless miss. Two conventions to try, in order:
  if (!path.extname(urlPath)) {
    //  1. flat-file export (Next export, Hugo, Jekyll): /about -> about.html
    var asHtml = target + '.html';
    if (fs.existsSync(asHtml)) return asHtml;
    //  2. client-routed SPA (Vite, CRA): every path serves the shell
    var shell = path.join(root, 'index.html');
    if (fs.existsSync(shell)) return shell;
  }

  return null;
}

http.createServer(function (req, res) {
  var urlPath;
  try {
    urlPath = decodeURIComponent(new URL(req.url, 'http://127.0.0.1').pathname);
  } catch (e) {
    urlPath = '/';
  }

  var file = resolveFile(urlPath);
  if (!file) {
    res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
    res.end('Not found');
    return;
  }

  var type = MIME[path.extname(file).toLowerCase()] || 'application/octet-stream';
  res.writeHead(200, { 'Content-Type': type, 'Cache-Control': 'no-store' });
  fs.createReadStream(file).pipe(res);
}).listen(port, '127.0.0.1', function () {
  console.log('[static-server] serving ' + root + ' on 127.0.0.1:' + port);
});
`;

/**
 * Start a static file server for `dir` on `port`.
 *
 * Returns the child process so the caller can kill it exactly the way it kills
 * a dev server — spawned detached on POSIX so killProcess can signal the whole
 * process group.
 */
export async function serveStaticDir(
  dir: string,
  port: number
): Promise<ChildProcess> {
  if (!existsSync(dir)) {
    throw new Error(`Static directory does not exist: ${dir}`);
  }
  if (!hasIndexHtml(dir)) {
    throw new Error(`Static directory has no index.html: ${dir}`);
  }

  log(`[static] serving ${dir} on port ${port}`);

  const proc = spawn(process.execPath, ["-e", CHILD_SERVER_SRC], {
    env: {
      ...process.env,
      SHIRODIFF_STATIC_ROOT: dir,
      SHIRODIFF_STATIC_PORT: String(port),
    },
    detached: process.platform !== "win32",
  });

  proc.stdout.on("data", (d) => process.stdout.write(d));
  proc.stderr.on("data", (d) => process.stderr.write(d));

  return proc;
}
