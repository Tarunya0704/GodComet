# VisualBot

GitHub App that posts before/after screenshots on every pull request with visual changes.

Phase 1 MVP — Next.js App Router only, hardcoded to screenshot `/`.

## How it works

On `pull_request.opened` or `pull_request.synchronize`:

1. Clone the repo at the **base** SHA.
2. `npm install && npm run build && npm start` on a random free port.
3. Playwright takes a full-page screenshot of `http://localhost:<port>/`.
4. Kill the server. Repeat for the **head** SHA on a different port.
5. `pixelmatch` the two PNGs.
6. If the change is `>= 0.1%`, post a PR comment with before / after / diff images.
   Otherwise post a green ✅ "No visual changes" comment.

Images are uploaded to an orphan branch `visualbot-assets` in the same repo and
referenced via `raw.githubusercontent.com`. This needs **Contents: write** on the
GitHub App.

## Tech stack

- Node 20+, TypeScript, ESM
- [Probot 13](https://probot.github.io/) for the GitHub App webhook plumbing
- Playwright (chromium) for screenshots
- `pixelmatch` + `pngjs` for pixel diffing
- `ssim.js` for structural similarity scoring (alongside pixelmatch)
- `sharp` for Lanczos crop/resize when before/after differ in shape
- Railway for hosting (see `Dockerfile`)

## Lineage

VisualBot's visual-comparison and screenshot logic is **ported from
GodComet's battle-tested Python pipeline** under `mcp-automation/`.
Specifically:

| TypeScript file | Source of logic | What was carried over |
|---|---|---|
| `src/differ.ts` | `mcp-automation/src/verification/visual_auditor.py` | Aspect-ratio mismatch handling (>10% AR diff → intelligent crop on the taller/wider side, then Lanczos resize). pixelmatch threshold = `0.1`. Three independent scores: pixelmatch ratio, pixel similarity (`1 - sum|a-b|/(size·255)`), and SSIM on grayscale. Composite score = `structural·0.5 + pixel·0.5` (no vision LLM in MVP). Diff-overlay strategy onto the AFTER image. |
| `src/screenshotter.ts` | `mcp-automation/src/verification/render_engine.py` | Animation-disable CSS injection. Configurable viewport (default 1440×900). 2s font-settle wait after networkidle. Chromium hardening flags. Both full-page (for human comment) AND viewport-only (for diff) captures. Min-size validity check (<100KB → suspect/retry). |
| `src/clone.ts` | `mcp-automation/src/tools/github_tool.py` | Explicit `user.email`/`user.name` git config. Per-command timeouts. stderr captured & surfaced. Fatal-vs-transient error classification (bad SHA / auth failure → no retry; network errors → retry). |
| `src/commenter.ts` | `production_figma_converter.py` (rate-limit) + `github_tool.py` (API patterns) | Every GitHub API call wrapped in exponential backoff `30·2^attempt → 30s, 60s, 120s` retrying only on 429 / 5xx / network errors. Comment now surfaces all three diff scores + viewport + normalization flags. |
| `src/bot.ts` | GodComet workflow executor pattern | Each stage runs through `timed()`, errors get tagged with `.stage`, and timings are listed in error comments. |
| `src/types.ts` | All of the above | Shared shapes (`ScreenshotResult`, `DiffResult`, `PageDiff`, `StageTiming`) and the constants we lifted directly: `PIXELMATCH_THRESHOLD=0.1`, `ASPECT_RATIO_MISMATCH_PCT=0.10`, `MIN_SCREENSHOT_BYTES=100KB`, `FONT_SETTLE_MS=2000`. |

What was deliberately **not** ported (slated for later phases):
- Vision-LLM analysis from `visual_auditor._vision_analysis` — Phase 3.
- `self_healer.fix_with_vision` code-repair loop — Phase 3.
- Figma/component-decomposer tooling — Phase 5.


## Project layout

```
visualbot/
├── src/
│   ├── index.ts          # Probot app entry point
│   ├── bot.ts            # Pipeline orchestrator
│   ├── clone.ts          # git clone at a specific SHA
│   ├── builder.ts        # npm install / build / start, wait for server
│   ├── screenshotter.ts  # Playwright screenshots
│   ├── differ.ts         # pixelmatch + diff overlay
│   ├── commenter.ts      # GitHub PR comments + asset upload
│   └── utils.ts          # ports, temp dirs, kill, timeouts, logging
├── Dockerfile
├── package.json
├── tsconfig.json
└── .env.example
```

## Local development

### 1. Create the GitHub App

Go to https://github.com/settings/apps/new and configure:

- **Webhook URL:** your smee.io proxy URL (see step 3)
- **Webhook secret:** any random string — save it
- **Permissions:**
  - Pull requests: **Read & write**
  - Contents: **Read & write** (needed to push assets to `visualbot-assets`)
  - Metadata: **Read** (default)
- **Subscribe to events:** Pull request

Generate a private key and download the `.pem`. Note the App ID.

### 2. Install on a test repo

Use a simple Next.js app:

```bash
npx create-next-app@latest visualbot-test
```

Push it to GitHub and install your app on it.

### 3. Configure env

```bash
cp .env.example .env
```

Fill in:

- `APP_ID` — from the GitHub App settings page
- `PRIVATE_KEY` — paste the contents of the `.pem`, or set `PRIVATE_KEY_PATH=/path/to/key.pem`
- `WEBHOOK_SECRET` — the secret you set in step 1
- `WEBHOOK_PROXY_URL` — create one at https://smee.io/new

### 4. Run

```bash
npm install
npx playwright install chromium
npm run dev
```

Open a PR on the test repo that changes some CSS, wait ~1–3 minutes, watch the
comment appear.

## Deploy on Railway

1. Push this repo to GitHub.
2. New Railway project → "Deploy from GitHub repo".
3. Set the same env vars (omit `WEBHOOK_PROXY_URL` in production — point the
   GitHub App's webhook URL at `https://<your-railway-app>.up.railway.app/`).
4. Railway will build using `Dockerfile`.

## Limits / known gotchas

- Pipeline times out at **5 minutes per PR**. Slow installs / builds will fail
  with an `❌` comment.
- Only screenshots `/`. Multi-page support comes in a later phase.
- Assumes `npm start` (or `npm run dev`) starts on `process.env.PORT`. Most
  Next.js apps do, but custom servers may not.
- The `visualbot-assets` orphan branch grows over time. Future work: prune old
  PR folders.

## Testing checklist

- [ ] PR that changes a background color → before/after/diff comment within 3 min
- [ ] PR that touches only README → ✅ "No visual changes"
- [ ] PR with a build error → ❌ comment with the build stderr
- [ ] Railway logs show clean execution, no hanging child processes
