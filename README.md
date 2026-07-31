# GodComet

A hotkey-driven AI assistant for developers. Hit a shortcut, describe what you want, and GodComet reaches into whatever tools it needs — Figma, GitHub, Vercel, Jira, your browser, your filesystem — to get it done, then checks its own work before handing it back to you.

The project is really three things living in one repo:

- **`godcomet/`** — the Electron desktop app: a floating command bar, a Python/FastAPI brain behind it, and browser/editor extensions that feed it context.
- **`mcp-automation/`** — the Python engine room. This is where the MCP tool server, the Figma-to-code pipeline, the visual verification loop, and the context-aware orchestrator ("Agentic OS") actually live.
- **`visualbot/`** — a standalone GitHub App, spun out of the visual-verification logic above, that comments before/after screenshots on pull requests.

Everything below reflects what's actually implemented in this repo today, not a roadmap.

---

## How it fits together

```
┌─────────────────────────────┐        ┌──────────────────────────────────┐
│         godcomet/            │        │          mcp-automation/          │
│  Electron desktop app         │        │       Python MCP tool server      │
│                               │  HTTP  │                                    │
│  ┌─────────────────────┐     │◀──────▶│  mcp_server.py  (40+ tools)       │
│  │  Command bar (React) │     │ :8001  │  agentic_os.py  (orchestrator)    │
│  └──────────┬────────────┘     │        │                                    │
│             │ IPC               │        │  context/                         │
│  ┌──────────▼────────────┐     │        │   ├─ context_aggregator.py        │
│  │  ai-brain.ts           │     │        │   ├─ desktop_vision.py            │
│  │  (command → backend)   │     │        │   └─ action_registry.py           │
│  └─────────────────────────┘     │        │                                    │
│                               │        │  verification/  (the visual moat) │
│  extensions/                  │        │   ├─ visual_auditor.py            │
│   ├─ chrome/  (tab + DOM ctx) │◀──WS──▶│   ├─ render_engine.py             │
│   ├─ vscode/  (file + git ctx)│  :8765 │   ├─ self_healer.py               │
│   └─ windows-context/         │        │   ├─ confidence_scorer.py         │
│      (active window, clip.)   │        │   └─ interactive_browser.py       │
└─────────────────────────────┘        │                                    │
                                        │  tools/  (Figma, GitHub, Vercel,  │
                                        │  Jira, Slack, AWS, browser, docs)  │
                                        └──────────────────────────────────┘

┌───────────────────────────────────────────────────┐
│                    visualbot/                       │
│  Standalone Probot GitHub App (TypeScript, separate  │
│  deploy). Ports the pixelmatch/SSIM diffing logic    │
│  from verification/ into a lightweight PR bot.        │
└───────────────────────────────────────────────────┘
```

The Electron app never talks to Figma, GitHub, or Vercel directly — it calls the FastAPI backend, which delegates to the MCP tool layer in `mcp-automation/`. That's also why `godcomet/backend/mcp_tools` exists as a symlink into `mcp-automation/src/tools` (see `setup_symlink.sh` / `.ps1` — run one of these after cloning).

---

## Repo layout

```
GodComet/
├── godcomet/                      # Electron desktop app
│   ├── main.js                    # legacy Electron entry (superseded, kept for reference)
│   ├── src/
│   │   ├── main/
│   │   │   ├── index.ts           # active entry: registers the global hotkey, owns the command window
│   │   │   ├── ai-brain.ts        # sends commands to the FastAPI backend, shapes results for the UI
│   │   │   ├── context.ts         # active-window / clipboard detection (early-stage)
│   │   │   └── integrations/      # thin clients: figma.ts, github.ts, jira.ts, slack.ts, vscode.ts, chrome.ts
│   │   ├── preload/                # contextBridge boundary between main and renderer
│   │   ├── renderer/               # React UI: CommandBar, FigmaWorkflow, ProgressTracker, Settings, Results
│   │   └── shared/                 # types + utils shared across processes
│   ├── backend/                    # FastAPI service the Electron app talks to
│   │   ├── brain.py                # main API: wires up mcp_server, workflow engine, websocket progress
│   │   ├── workflow_state_machine.py / workflow_executor.py
│   │   ├── websocket_server.py     # pushes live step-by-step progress to the UI
│   │   └── mcp_tools -> ../../mcp-automation/src/tools   (symlink)
│   ├── extensions/
│   │   ├── chrome/                 # MV3 extension: active tab URL, console errors, DOM snapshot
│   │   ├── vscode/                 # reports open file, selection, cursor, git branch over WebSocket
│   │   └── windows-context/        # OS-level active window / clipboard / running-apps polling
│   └── lib/context-detector.js     # cross-platform context glue used by the extensions
│
├── mcp-automation/                 # Python engine room
│   ├── src/
│   │   ├── mcp_server.py           # MCP server exposing 40+ tools (browser, AWS, files, Figma, Jira,
│   │   │                           #   GitHub, Vercel, workflows, code analysis, web scraping…)
│   │   ├── agentic_os.py           # ties context + action_registry + verification into one command loop
│   │   ├── ai_client.py            # Claude / Groq client wrapper (see model notes below)
│   │   ├── context/
│   │   │   ├── context_aggregator.py  # polls VS Code, Chrome, desktop, clipboard in parallel
│   │   │   ├── desktop_vision.py      # screenshots the desktop, asks a vision model what's on it
│   │   │   └── action_registry.py     # maps aggregated context → a ranked list of runnable actions
│   │   ├── verification/           # closed-loop visual QA (see below)
│   │   └── tools/                  # one file per integration/capability (see Integrations table)
│   ├── documents/, image_cache/    # working directories for generated artifacts
│   └── requirements.txt
│
├── visualbot/                      # Standalone GitHub App (Node 20, TypeScript, ESM, Probot)
│   ├── src/{bot,clone,builder,screenshotter,differ,commenter}.ts
│   ├── Dockerfile                  # deployed independently (Railway)
│   └── README.md                   # its own setup guide + a table mapping each file back to the
│                                    #   mcp-automation module its logic was ported from
│
├── setup_symlink.sh / .ps1         # recreates godcomet/backend/mcp_tools after a fresh clone
└── *.md                            # design notes / architecture write-ups from the build process
```

---

## What each layer actually does

### 1. The command bar (Electron)

`index.ts` registers a global hotkey (`Cmd+Space` on macOS, `Ctrl+Space` elsewhere) that pops a frameless, always-on-top `BrowserWindow` and hides itself again on blur. Whatever you type gets handed to `ai-brain.ts`, which posts it to the FastAPI backend at `http://localhost:8001` along with whatever context is available, waits for the result, and routes it back to the renderer over IPC. The renderer (`CommandBar.tsx`, `FigmaWorkflow.tsx`, `ProgressTracker.tsx`, `Results.tsx`) renders the response and streams live step progress from the backend's WebSocket channel.

### 2. Context awareness

Three independent sources feed context into the system, and `context_aggregator.py` polls them concurrently:

- **Chrome extension** (`extensions/chrome/`) — active tab URL, page title, console errors, DOM structure, forwarded over a WebSocket on port 8765.
- **VS Code extension** (`extensions/vscode/`) — current file, language, selection, cursor position, git branch.
- **Desktop layer** (`extensions/windows-context/`, `desktop_vision.py`) — active window and clipboard via OS APIs, plus an optional screenshot-and-ask-a-vision-model step for a coarser "what is the user looking at" read when the structured signals aren't enough.

`action_registry.py` takes that merged context and matches it against a table of ~12 registered actions (extract a Figma design, generate code from it, fix console errors, deploy to Vercel, run the full pipeline, …), ranking them by relevance so the assistant can suggest — or in `agentic_os.py`, auto-execute — the most likely next step.

### 3. Figma → code

`tools/figma_to_website_tool.py` and `tools/production_figma_converter.py` pull a Figma file via the Figma API, extract layout/style metadata plus a reference screenshot, and hand it to an LLM (Groq by default, see below) to generate a Next.js/React project. `component_decomposer.py` exists to break a design into per-component generation passes rather than a single monolithic prompt, which holds up better on larger frames.

### 4. Visual Auditor — the verification loop

This is the part the rest of the project is built around: generated code doesn't ship on faith, it gets checked against the design it came from.

`render_engine.py` boots a headless Chromium via Playwright, starts a local dev server for the generated project, waits for network-idle plus a font-settle buffer, disables CSS animations for determinism, and captures a full-page screenshot at a configurable viewport (1440×900 by default).

`visual_auditor.py` then compares that render against the original Figma screenshot three ways:

- **SSIM** — structural similarity on grayscale images (`skimage.metrics.structural_similarity`)
- **Pixel diff** — normalized pixel-wise difference
- **Vision model** — GPT-4o or Claude is shown both images and asked to score layout/color/typography and point out concrete issues

The overall score is a weighted blend — `structural × 0.25 + pixel × 0.25 + vision × 0.50` when a vision model is configured, or an even `structural × 0.5 + pixel × 0.5` fallback when it isn't. A configurable threshold (default `0.95`) decides pass/fail.

Below threshold, `self_healer.py` turns the auditor's structured issue list into a corrective prompt ("button color must be exactly #3B82F6", "container padding must be exactly 24px") and triggers a regeneration — capped at 3 iterations so a stubborn diff can't loop forever. `confidence_scorer.py` provides the underlying metric primitives (SSIM, pixel similarity, color accuracy, layout-via-edge-detection) plus a human-readable A–F interpretation of the final score. `interactive_browser.py` goes one step further than pixels: it can drive the rendered page — click, type, wait, assert — to confirm the thing actually *works*, not just that it *looks* right.

### 5. Agentic OS — the orchestrator

`agentic_os.py` is the glue: on a hotkey press, it gathers context, asks `action_registry.py` what's runnable, either presents the options or auto-runs the top match, and streams progress back through the same channel the Electron UI listens on. The "Figma to production" action chains everything above — extract → generate → render → audit → self-heal (if needed) → deploy → open a PR — as one command.

### 6. Integrations

Each of these lives as its own module in `mcp-automation/src/tools/` (and has a thin mirror in `godcomet/src/main/integrations/` for the Electron side where relevant):

| Integration | File(s) | What it's used for |
|---|---|---|
| Figma | `figma_mcp_client.py`, `figma_to_website_tool.py` | Pull file/frame data + screenshots |
| GitHub | `github_tool.py` | Create repos, push generated code, generate READMEs, open PRs |
| Vercel | `vercel_tool.py` | Deploy generated projects, list deployments |
| Jira | `jira_tool.py`, `jira_browser_automation.py` | Create issues/visual tickets from screenshots |
| Slack | `godcomet/src/main/integrations/slack.ts` | Notifications from the Electron side |
| AWS | `aws_tool.py` | S3 bucket create/list (optional, boto3) |
| Browser | `browser_tool.py`, `web_scraper_tool.py` | Navigation, screenshots, scraping, table extraction |
| Code | `code_analysis_tool.py` | Analyze / fix / refactor / document / generate tests for existing code |
| Docs | `document_generator_tool.py`, `document_parser.py` | Turn specs (docx/pdf/pptx) into structured output |

All of it is exposed through `mcp_server.py` as MCP tools, so it's callable both from the Electron app's backend and from any other MCP-compatible client.

### 7. VisualBot — the spin-off

`visualbot/` is a separately deployed GitHub App (Probot, Node 20, TypeScript/ESM) that does a focused version of step 4 for pull requests: on `opened`/`synchronize`, it builds the base and head SHAs, screenshots both with Playwright, diffs them with `pixelmatch` + `ssim.js`, and comments the before/after/diff images on the PR (or a green "no visual changes" check if nothing moved). It deliberately reuses the exact constants and thresholds from the Python verification module — see the table in [`visualbot/README.md`](visualbot/README.md) mapping each TypeScript file back to the Python it was ported from. It has its own `Dockerfile` and deploys independently (Railway).

---

## Tech stack

| Layer | Stack |
|---|---|
| Desktop shell | Electron 28, TypeScript, Vite, React 18 |
| Desktop backend | Python, FastAPI, WebSockets, SQLite |
| AI / codegen | Groq SDK (fast/free-tier default), Anthropic Claude, OpenAI GPT-4o (vision + fallback) |
| Browser automation | Playwright (Chromium) |
| Image comparison | scikit-image (SSIM), OpenCV, pixelmatch, sharp |
| Extensions | Chrome MV3, VS Code extension API |
| VisualBot | Probot 13, TypeScript/ESM, Playwright, ssim.js, sharp |
| Integrations | Figma API, GitHub (PyGithub), Vercel API, Jira API, Slack, AWS (boto3) |

---

## Getting started

### Prerequisites

- Node.js 20+
- Python 3.10+
- A Figma personal access token, and any of the API keys below that you plan to exercise

### 1. Clone and relink the shared tools

The Electron backend imports Python tools from `mcp-automation/` through a symlink that isn't tracked in git:

```bash
./setup_symlink.sh        # macOS/Linux
# or
.\setup_symlink.ps1       # Windows
```

### 2. Set up the Python engine

```bash
cd mcp-automation
python -m venv venv && source venv/bin/activate   # or your preferred env manager
pip install -r requirements.txt
playwright install chromium
cp .env.example .env   # if present — otherwise create .env with the keys below
```

Minimum viable `.env`:

```bash
ANTHROPIC_API_KEY=...      # primary model for code generation / vision
GROQ_API_KEY=...           # fast, cheap fallback for code generation
FIGMA_TOKEN=...
GITHUB_TOKEN=...
VERCEL_TOKEN=...
# optional: OPENAI_API_KEY, JIRA_URL/EMAIL/API_TOKEN, AWS_ACCESS_KEY_ID/SECRET_ACCESS_KEY
```

### 3. Run the backend

```bash
cd godcomet/backend
pip install -r requirements.txt
python brain.py    # FastAPI on :8001
```

### 4. Run the desktop app

```bash
cd godcomet
npm install
npm run dev
```

Press the hotkey (`Cmd+Space` / `Ctrl+Space`) once the app is running — you should see the command window and a "GodComet ready" log line.

### 5. (Optional) VisualBot

VisualBot is deployed and configured independently of the desktop app — see [`visualbot/README.md`](visualbot/README.md) for creating the GitHub App, wiring a webhook, and running it locally with `smee-client`.

---

## A note on project state

This is an actively evolving codebase, not a polished 1.0. A few things worth knowing before you dig in:

- `godcomet/main.js` and parts of `context.ts` are earlier iterations kept for reference — `src/main/index.ts` and `ai-brain.ts` are the live entry points.
- The visual-verification threshold, iteration limits, and viewport defaults are all configurable (`VISUAL_AUDIT_THRESHOLD`, `VISUAL_AUDIT_MAX_ITERATIONS`, etc.) rather than hardcoded, so tune them per project.
- `visualbot/` is the most production-shaped piece of the three — it's the one meant to run unattended on other people's repos, which is why its logic was hardened and ported out of the exploratory Python pipeline rather than imported directly.

The other `.md` files at the repo root (`VISUAL_AUDITOR_ARCHITECTURE.md`, `AGENTIC_OS_COMPLETE.md`, `IMPLEMENTATION_COMPLETE.md`, `DEMO_VC_PITCH.md`) are design notes and a pitch script written during development — useful for the *why* behind the verification loop's design, but this README is the source of truth for what's actually running.
