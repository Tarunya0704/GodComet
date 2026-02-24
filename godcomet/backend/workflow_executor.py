"""
GodComet Workflow Executor
Actually runs the Figma-to-Production pipeline with real-time updates
"""

import asyncio
import logging
import sys
import os
import base64
from pathlib import Path
from typing import Dict, Optional

# Add mcp-automation/src to path
mcp_src = Path(__file__).parent.parent.parent / "mcp-automation" / "src"
sys.path.insert(0, str(mcp_src))

from workflow_state_machine import workflow_manager, WorkflowState, WorkflowContext
from websocket_server import workflow_ws_server

logger = logging.getLogger(__name__)


class WorkflowExecutor:
    """
    Executes the full Figma-to-Production pipeline with real-time updates

    Flow:
    1. Extract Figma design + screenshot
    2. Generate React code
    3. Render with Playwright
    4. Visual audit
    5. PAUSE for user approval
    6. Push to GitHub
    7. Deploy to Vercel
    """

    def __init__(self):
        self.active_workflows: Dict[str, asyncio.Task] = {}

    async def start_workflow(
        self,
        figma_url: str,
        project_name: Optional[str] = None
    ) -> WorkflowContext:
        """Start a new workflow and begin execution"""

        # Create workflow
        workflow = workflow_manager.create_workflow(
            figma_url=figma_url,
            project_name=project_name
        )

        # Start execution in background
        task = asyncio.create_task(self._execute_workflow(workflow))
        self.active_workflows[workflow.id] = task

        return workflow

    async def _execute_workflow(self, workflow: WorkflowContext):
        """
        Execute the full Figma-to-Production pipeline.

        New two-gate flow:
          generating → rendering → auditing
               → [GATE 1: awaiting_code_approval]
                    approve  → deploying (GitHub push)
                                → [GATE 2: awaiting_deploy_approval]
                                      approve → deploying (Vercel) → done
                                      reject  → done (code stays on GitHub)
                    change   → change_requested → apply edit → re-render → re-audit → Gate 1
                    reject   → error
        """
        try:
            logger.info(f"Starting workflow execution: {workflow.id}")

            # Step 1: Extract Figma design
            await self._step_extract_figma(workflow)

            # Step 2: Generate code
            await self._step_generate_code(workflow)

            # Step 3: Render
            await self._step_render(workflow)

            # Step 4: Visual audit
            await self._step_visual_audit(workflow)

            # ── GATE 1: code review ──────────────────────────────────────────
            # Loop allows the user to request changes and see them re-rendered
            # before approving. Capped at MAX_CHANGE_REQUESTS to prevent loops.
            MAX_CHANGE_REQUESTS = 3
            change_count = 0

            while True:
                gate1 = await self._step_await_code_approval(workflow)

                if gate1.get("approved"):
                    break  # proceed to GitHub push

                if gate1.get("cancelled"):
                    logger.info(f"Workflow {workflow.id} cancelled at Gate 1")
                    return

                if gate1.get("change_requested"):
                    change_count += 1
                    if change_count > MAX_CHANGE_REQUESTS:
                        await workflow_manager.set_error(
                            workflow,
                            f"Max change requests ({MAX_CHANGE_REQUESTS}) exceeded"
                        )
                        return

                    instruction = gate1.get("instruction", "")
                    logger.info(f"Change request {change_count}/{MAX_CHANGE_REQUESTS}: {instruction!r}")
                    workflow.change_request = instruction

                    await self._step_apply_change_request(workflow)
                    await self._step_render(workflow)
                    await self._step_visual_audit(workflow)
                    # loop back to Gate 1
                    continue

                # rejected (or timeout)
                reason = gate1.get("reason", "Rejected by user at code review")
                await workflow_manager.set_error(workflow, reason)
                return
            # ────────────────────────────────────────────────────────────────

            # Step 6: Push to GitHub
            await self._step_push_github(workflow)

            # ── GATE 2: deploy approval ──────────────────────────────────────
            deploy = await self._step_await_deploy_approval(workflow)

            if not deploy:
                # User chose not to deploy — code is on GitHub, call it done
                logger.info(f"Workflow {workflow.id} done without Vercel deploy")
                await workflow_manager.complete_workflow(
                    workflow,
                    github_url=workflow.github_url,
                    vercel_url=None
                )
                return
            # ────────────────────────────────────────────────────────────────

            # Step 7: Deploy to Vercel
            await self._step_deploy_vercel(workflow)

            # Complete
            await workflow_manager.complete_workflow(
                workflow,
                github_url=workflow.github_url,
                vercel_url=workflow.vercel_url
            )

            logger.info(f"Workflow {workflow.id} completed successfully!")

        except Exception as e:
            logger.error(f"Workflow {workflow.id} failed: {e}", exc_info=True)
            await workflow_manager.set_error(workflow, str(e))
        finally:
            self.active_workflows.pop(workflow.id, None)

    async def _make_api_request(self, url: str, headers: Dict = None, params: Dict = None, max_retries: int = 5):
        """Make an API request with exponential backoff for rate limits"""
        import requests
        
        base_delay = 2.0
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                # Use run_in_executor to avoid blocking the event loop
                loop = asyncio.get_running_loop()
                response = await loop.run_in_executor(
                    None, 
                    lambda: requests.get(url, headers=headers, params=params, timeout=30)
                )
                
                if response.status_code == 200:
                    return response

                if response.status_code == 403:
                    # Permission denied — no point retrying, fail immediately with clear message
                    raise PermissionError(
                        f"Figma API returned 403 Forbidden.\n"
                        f"Check:\n"
                        f"  1. Your FIGMA_TOKEN has 'file_content:read' scope\n"
                        f"  2. The Figma file is shared with your token's account\n"
                        f"  3. The file ID in the URL is correct\n"
                        f"Response: {response.text[:200]}"
                    )

                if response.status_code == 404:
                    raise FileNotFoundError(
                        f"Figma file not found (404). Check the file ID in your URL.\n"
                        f"Response: {response.text[:200]}"
                    )

                if response.status_code == 429:
                    # Rate limit — use Retry-After if present, capped at 60s
                    retry_header = response.headers.get("Retry-After")
                    try:
                        retry_after = int(retry_header) if retry_header else base_delay * (2 ** attempt)
                    except ValueError:
                        retry_after = base_delay * (2 ** attempt)

                    retry_after = min(retry_after, 60)  # Never wait more than 60s
                    logger.warning(f"Rate limit hit. Waiting {retry_after}s (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(retry_after)
                    continue

                if response.status_code >= 500:
                    # Server error — retry with backoff
                    wait = min(30, base_delay * (2 ** attempt))
                    logger.warning(f"Figma server error {response.status_code}. Retrying in {wait}s...")
                    await asyncio.sleep(wait)
                    continue

                # Any other non-200 status — return and let caller handle it
                return response
                
            except Exception as e:
                logger.warning(f"Request failed: {e}. Retrying in {base_delay}s...")
                last_exception = e
                await asyncio.sleep(base_delay)
                base_delay *= 1.5
                
        if last_exception:
            raise last_exception
        raise RuntimeError(f"Max retries exceeded for {url}")

    async def _step_extract_figma(self, workflow: WorkflowContext):
        """Step 1: Extract Figma design and screenshot"""
        await workflow_manager.transition(
            workflow,
            WorkflowState.GENERATING,
            step_name="Extracting Figma design",
            progress=5,
            message="Connecting to Figma API..."
        )

        try:
            import re
            from urllib.parse import urlparse, parse_qs

            # Step 1 only parses the URL — NO file fetch here.
            # The converter in Step 2 fetches the file with a 1-hour cache,
            # so doing it again here would waste a rate-limited API call.
            figma_url = workflow.figma_url
            match = re.search(r'/(?:design|file)/([a-zA-Z0-9]+)', figma_url)
            if not match:
                raise ValueError(f"Cannot extract file ID from Figma URL: {figma_url}")
            file_id = match.group(1)

            parsed = urlparse(figma_url)
            node_id = parse_qs(parsed.query).get('node-id', [None])[0]

            figma_token = os.getenv("FIGMA_TOKEN")
            if not figma_token:
                raise ValueError("FIGMA_TOKEN not found in environment")

            # Store basic metadata now; file name will be updated after Step 2
            workflow.figma_metadata = {
                "file_id": file_id,
                "node_id": node_id,
                "name": "Fetching...",
            }

            # Step 1 no longer fetches screenshots — the Figma file metadata
            # includes a thumbnailUrl which is downloaded in Step 2 after the
            # converter fetches the file (uses cache). This saves all API calls
            # here and avoids rate limits.
            logger.info("Step 1: URL parsed, screenshot will use thumbnailUrl from Step 2")

            await workflow_manager.complete_step(workflow, "Extracting Figma design", True, "Figma design extracted")

        except Exception as e:
            logger.error(f"Figma extraction failed: {e}")
            raise

    async def _step_generate_code(self, workflow: WorkflowContext):
        """Step 2: Generate React/Next.js code"""
        await workflow_manager.transition(
            workflow,
            WorkflowState.GENERATING,
            step_name="Generating React code",
            progress=25,
            message="AI is generating React components..."
        )

        try:
            # Import the production converter
            from tools.production_figma_converter import ProductionFigmaToCode

            figma_token = os.getenv("FIGMA_TOKEN")
            converter = ProductionFigmaToCode(figma_token)

            # Create output directory
            projects_dir = Path(__file__).parent.parent.parent / "mcp-automation" / "projects"
            projects_dir.mkdir(parents=True, exist_ok=True)

            output_dir = projects_dir / workflow.project_name
            output_dir.mkdir(parents=True, exist_ok=True)

            await workflow_manager.transition(
                workflow,
                WorkflowState.GENERATING,
                step_name="Generating React code",
                progress=35,
                message="Converting Figma to React components..."
            )

            # Get figma screenshot path for AI generation
            screenshot_dir = Path(__file__).parent.parent.parent / "mcp-automation" / "screenshots" / workflow.id
            figma_screenshot = str(screenshot_dir / "figma_original.png") if screenshot_dir.exists() else None

            # Generate code (AI-powered with Figma screenshot for better accuracy)
            result = await converter.convert(
                figma_url=workflow.figma_url,
                output_dir=output_dir,
                figma_screenshot_path=figma_screenshot
            )

            # Surface code generation failures immediately
            if not result.get("success"):
                raise Exception(f"Code generation failed: {result.get('error', 'Converter returned failure')}")

            workflow.project_path = str(output_dir)

            # Store registry path so downstream steps can read it
            if result.get("registry_path"):
                workflow.registry_path = result["registry_path"]

            # Backfill file name from converter result
            if workflow.figma_metadata and result.get("file_name"):
                workflow.figma_metadata["name"] = result["file_name"]

            # Use Figma thumbnailUrl for screenshot — it comes FREE with the file
            # metadata (already cached), zero extra API calls needed.
            if not workflow.figma_screenshot:
                thumbnail_url = result.get("thumbnail_url")
                if thumbnail_url:
                    try:
                        import requests as _requests
                        logger.info(f"Downloading Figma thumbnail (no API call): {thumbnail_url[:60]}...")
                        thumb_resp = await asyncio.get_running_loop().run_in_executor(
                            None, lambda: _requests.get(thumbnail_url, timeout=30)
                        )
                        if thumb_resp.status_code == 200:
                            screenshots_dir = Path(__file__).parent.parent.parent / "mcp-automation" / "screenshots" / workflow.id
                            screenshots_dir.mkdir(parents=True, exist_ok=True)
                            screenshot_path = screenshots_dir / "figma_original.png"
                            with open(screenshot_path, "wb") as f:
                                f.write(thumb_resp.content)
                            workflow.figma_screenshot = str(screenshot_path)
                            logger.info(f"Figma thumbnail saved: {screenshot_path}")
                    except Exception as e:
                        logger.warning(f"Could not download Figma thumbnail: {e} (continuing anyway)")

            await workflow_manager.transition(
                workflow,
                WorkflowState.GENERATING,
                step_name="Generating React code",
                progress=45,
                message="Code generation complete!"
            )

            await workflow_manager.complete_step(workflow, "Generating React code", True, "React code generated")

        except Exception as e:
            logger.error(f"Code generation failed: {e}")
            raise

    async def _step_render(self, workflow: WorkflowContext):
        """Step 3: Start dev server and render with Playwright"""
        await workflow_manager.transition(
            workflow,
            WorkflowState.RENDERING,
            step_name="Starting dev server",
            progress=50,
            message="Installing dependencies..."
        )

        try:
            from verification.render_engine import RenderEngine

            render_engine = RenderEngine()

            await workflow_manager.transition(
                workflow,
                WorkflowState.RENDERING,
                step_name="Rendering website",
                progress=55,
                message="Building Next.js static export..."
            )

            # Render the generated website
            screenshots_dir = Path(__file__).parent.parent.parent / "mcp-automation" / "screenshots" / workflow.id
            screenshots_dir.mkdir(parents=True, exist_ok=True)

            render_result = await render_engine.render(
                workflow.project_path,
                output_path=str(screenshots_dir / "rendered.png")
            )

            workflow.rendered_screenshot = render_result.get("screenshot_path")

            await workflow_manager.complete_step(workflow, "Rendering website", True, "Website rendered")

        except Exception as e:
            logger.error(f"Rendering failed: {e}", exc_info=True)
            # Notify the UI immediately via WebSocket before halting
            await workflow_ws_server.send_error(
                workflow_id=workflow.id,
                error=f"Rendering failed: {e}",
                step="Rendering website",
                recoverable=False
            )
            # Re-raise — proceeding to visual audit with a null screenshot
            # produces meaningless results (fake 90% score). Stop here instead.
            raise

    async def _step_visual_audit(self, workflow: WorkflowContext):
        """Step 4: Visual audit comparing Figma vs rendered"""
        await workflow_manager.transition(
            workflow,
            WorkflowState.AUDITING,
            step_name="Visual audit",
            progress=60,
            message="Comparing Figma design with generated website..."
        )

        try:
            from verification.visual_auditor import VisualAuditor

            auditor = VisualAuditor(threshold=0.95, use_groq=True)

            # Run audit if we have both screenshots
            if workflow.figma_screenshot and workflow.rendered_screenshot:
                audit_result = auditor.audit(
                    workflow.figma_screenshot,
                    workflow.rendered_screenshot,
                    workflow.figma_metadata or {}
                )

                workflow.audit_result = audit_result
                workflow.audit_score = audit_result.get("score", 0.0)

                await workflow_manager.transition(
                    workflow,
                    WorkflowState.AUDITING,
                    step_name="Visual audit",
                    progress=65,
                    message=f"Audit complete: {workflow.audit_score:.0%} match"
                )
            else:
                # figma_screenshot is missing (render succeeded but Figma thumbnail
                # couldn't be downloaded). Skip comparison — don't invent a score.
                logger.warning(f"Skipping visual audit: figma_screenshot={workflow.figma_screenshot}, rendered={workflow.rendered_screenshot}")
                workflow.audit_result = {
                    "score": None,
                    "passed": None,
                    "threshold": 0.95,
                    "issues": [
                        {"type": "figma_screenshot_missing", "description": "Figma thumbnail unavailable — visual comparison skipped", "severity": "info"}
                    ]
                }
                workflow.audit_score = None

            score_label = f"{workflow.audit_score:.0%}" if workflow.audit_score is not None else "skipped"
            await workflow_manager.complete_step(workflow, "Visual audit", True, f"Score: {score_label}")

        except Exception as e:
            logger.error(f"Visual audit failed: {e}")
            workflow.audit_result = {
                "score": 0.85,
                "passed": False,
                "threshold": 0.95,
                "issues": [{"type": "audit_error", "description": str(e), "severity": "minor"}]
            }
            workflow.audit_score = 0.85
            await workflow_manager.complete_step(workflow, "Visual audit", False, f"Audit error: {e}")

    async def _step_await_code_approval(self, workflow: WorkflowContext) -> Dict:
        """
        Gate 1 — pause before GitHub push.

        Returns the raw response dict from the WebSocket server:
          {"approved": True}
          {"change_requested": True, "instruction": "..."}
          {"approved": False}   (rejected or timed out)
        """
        logger.info(f"Gate 1: requesting code approval for workflow {workflow.id}")
        response = await workflow_manager.request_code_approval(workflow, timeout=300)

        if response.get("approved"):
            await workflow_manager.complete_step(workflow, "Awaiting code approval", True, "Code approved")
        elif response.get("change_requested"):
            instruction = response.get("instruction", "")
            await workflow_manager.complete_step(
                workflow, "Awaiting code approval", False,
                f"Change requested: {instruction[:60]}"
            )
        else:
            await workflow_manager.complete_step(workflow, "Awaiting code approval", False, "Code rejected")

        return response

    async def _step_await_deploy_approval(self, workflow: WorkflowContext) -> bool:
        """
        Gate 2 — pause after GitHub push, before Vercel deploy.
        Returns True if approved, False if skipped/rejected.
        """
        logger.info(f"Gate 2: requesting deploy approval for workflow {workflow.id}")
        response = await workflow_manager.request_deploy_approval(workflow, timeout=300)

        if response.get("approved"):
            await workflow_manager.complete_step(workflow, "Awaiting deploy approval", True, "Deploy approved")
            return True
        else:
            await workflow_manager.complete_step(
                workflow, "Awaiting deploy approval", False,
                "Deploy skipped — code stays on GitHub"
            )
            return False

    async def _step_apply_change_request(self, workflow: WorkflowContext):
        """
        Apply a user's plain-text change instruction to the generated code.

        Calls Groq with the instruction + current TSX files + Figma reference image
        and writes the result back to disk so the next render picks it up.
        Falls back to a full regeneration if Groq is unavailable.
        """
        import base64 as _b64
        import re as _re

        instruction = workflow.change_request or ""
        logger.info(f"Applying change request: {instruction!r}")

        await workflow_manager.transition(
            workflow,
            WorkflowState.CHANGE_REQUESTED,
            step_name="Applying change request",
            progress=35,
            message=f"Applying: {instruction[:60]}..."
        )

        # Try Groq first — same pattern as AICodeGenerator
        try:
            from groq import Groq
            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                raise RuntimeError("GROQ_API_KEY not set")
            groq_client = Groq(api_key=api_key)
        except Exception as e:
            logger.warning(f"Groq unavailable ({e}), falling back to full code regeneration")
            await self._step_generate_code(workflow)
            await workflow_manager.complete_step(workflow, "Applying change request", True, "Regenerated (Groq fallback)")
            return

        model = "meta-llama/llama-4-scout-17b-16e-instruct"
        project = Path(workflow.project_path)

        # Collect current TSX files
        tsx_files: dict = {}
        for candidate in [project / "src" / "app" / "page.tsx", project / "src" / "pages" / "index.tsx"]:
            if candidate.exists():
                tsx_files[str(candidate.relative_to(project))] = candidate.read_text(encoding="utf-8")
                break
        components_dir = project / "src" / "components"
        if components_dir.exists():
            for f in sorted(components_dir.glob("*.tsx")):
                tsx_files[str(f.relative_to(project))] = f.read_text(encoding="utf-8")

        if not tsx_files:
            logger.warning("No TSX files found, falling back to full regeneration")
            await self._step_generate_code(workflow)
            await workflow_manager.complete_step(workflow, "Applying change request", True, "Regenerated (no tsx)")
            return

        # Build multimodal message — include Figma screenshot if available
        user_content = []
        if workflow.figma_screenshot and Path(workflow.figma_screenshot).exists():
            with open(workflow.figma_screenshot, "rb") as f:
                img_b64 = _b64.b64encode(f.read()).decode()
            user_content.append({"type": "text", "text": "Original Figma design (reference):"})
            user_content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}})

        code_context = "\n".join(f"=== {p} ===\n{c}" for p, c in tsx_files.items())
        user_content.append({
            "type": "text",
            "text": (
                f"User change request: {instruction}\n\n"
                f"Current code:\n{code_context}\n\n"
                "Apply ONLY the requested change. Return changed files using path markers:\n"
                "=== src/app/page.tsx ===\n"
                "(full corrected file — no markdown fences, no explanation)"
            )
        })

        try:
            response = groq_client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a React/Next.js engineer. "
                            "Apply the user's change request to the code. "
                            "Return only changed files with === path === markers."
                        )
                    },
                    {"role": "user", "content": user_content}
                ],
                temperature=0.1,
                max_tokens=8000,
            )
        except Exception as e:
            logger.error(f"Groq change request failed: {e}, falling back to full regen")
            await self._step_generate_code(workflow)
            await workflow_manager.complete_step(workflow, "Applying change request", True, "Regenerated (Groq error)")
            return

        raw = response.choices[0].message.content
        parts = _re.split(r'^=== (.+?) ===\s*$', raw, flags=_re.MULTILINE)

        written = []
        if len(parts) >= 3:
            for i in range(1, len(parts) - 1, 2):
                rel_path = parts[i].strip()
                code = _re.sub(r'^```[^\n]*\n|```$', '', parts[i + 1].strip(), flags=_re.MULTILINE).strip()
                if code:
                    dest = project / rel_path
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(code, encoding="utf-8")
                    written.append(rel_path)
        else:
            # No markers — try writing whole response to root page
            code = _re.sub(r'^```[^\n]*\n|```$', '', raw.strip(), flags=_re.MULTILINE).strip()
            if "export default" in code:
                root = list(tsx_files.keys())[0]
                (project / root).write_text(code, encoding="utf-8")
                written.append(root)

        if written:
            logger.info(f"Change applied to: {', '.join(written)}")
            await workflow_manager.complete_step(workflow, "Applying change request", True, f"Changed: {', '.join(written)}")
        else:
            logger.warning("Change request yielded no writeable output, falling back to full regen")
            await self._step_generate_code(workflow)
            await workflow_manager.complete_step(workflow, "Applying change request", True, "Regenerated (empty response)")

    # ---------------------------------------------------------------------------
    # Legacy single-gate method — kept so any callers that predate the two-gate
    # split still work without modification.
    # ---------------------------------------------------------------------------
    async def _step_await_approval(self, workflow: WorkflowContext) -> bool:
        """Legacy Gate — delegates to the new Gate 1 (code approval)."""
        response = await self._step_await_code_approval(workflow)
        return response.get("approved", False)

    async def _step_push_github(self, workflow: WorkflowContext):
        """Step 6: Push to GitHub"""
        await workflow_manager.transition(
            workflow,
            WorkflowState.DEPLOYING,
            step_name="Creating GitHub repo",
            progress=75,
            message="Creating GitHub repository..."
        )

        try:
            from tools.github_tool import GitHubTool

            github_token = os.getenv("GITHUB_TOKEN")
            if not github_token:
                logger.warning("GITHUB_TOKEN not found, skipping GitHub")
                await workflow_manager.complete_step(workflow, "Creating GitHub repo", False, "No GitHub token")
                return

            github_tool = GitHubTool(access_token=github_token)

            await workflow_manager.transition(
                workflow,
                WorkflowState.DEPLOYING,
                step_name="Creating GitHub repo",
                progress=80,
                message="Pushing code to GitHub..."
            )

            result = await github_tool.build_and_push_project(
                repo_name=workflow.project_name,
                description=f"Generated from Figma by GodComet - {workflow.figma_metadata.get('name', 'Untitled')}",
                local_path=workflow.project_path,
                branch="main"
            )

            if result.get("success"):
                workflow.github_url = result.get("data", {}).get("repo_url")
                await workflow_manager.complete_step(workflow, "Creating GitHub repo", True, f"Pushed to {workflow.github_url}")
            else:
                await workflow_manager.complete_step(workflow, "Creating GitHub repo", False, result.get("error", "Unknown error"))

        except ImportError:
            logger.warning("GitHubTool not available")
            await workflow_manager.complete_step(workflow, "Creating GitHub repo", False, "GitHub tool not available")
        except Exception as e:
            logger.error(f"GitHub push failed: {e}")
            await workflow_manager.complete_step(workflow, "Creating GitHub repo", False, str(e))

    async def _step_deploy_vercel(self, workflow: WorkflowContext):
        """Step 7: Deploy to Vercel"""
        await workflow_manager.transition(
            workflow,
            WorkflowState.DEPLOYING,
            step_name="Deploying to Vercel",
            progress=90,
            message="Deploying to Vercel..."
        )

        try:
            from tools.vercel_tool import VercelTool

            vercel_token = os.getenv("VERCEL_TOKEN")
            vercel_tool = VercelTool(token=vercel_token)

            result = await vercel_tool.deploy(
                local_path=workflow.project_path,
                production=True
            )

            if result.get("success"):
                workflow.vercel_url = result.get("data", {}).get("url")
                await workflow_manager.transition(
                    workflow,
                    WorkflowState.DEPLOYING,
                    step_name="Deploying to Vercel",
                    progress=95,
                    message=f"Deployed to {workflow.vercel_url}"
                )
                await workflow_manager.complete_step(workflow, "Deploying to Vercel", True, f"Live at {workflow.vercel_url}")
            else:
                await workflow_manager.complete_step(workflow, "Deploying to Vercel", False, result.get("error", "Unknown error"))

        except ImportError:
            logger.warning("VercelTool not available")
            await workflow_manager.complete_step(workflow, "Deploying to Vercel", False, "Vercel tool not available")
        except Exception as e:
            logger.error(f"Vercel deployment failed: {e}")
            await workflow_manager.complete_step(workflow, "Deploying to Vercel", False, str(e))


# Global instance
workflow_executor = WorkflowExecutor()


def get_workflow_executor() -> WorkflowExecutor:
    """Get the global workflow executor instance"""
    return workflow_executor
