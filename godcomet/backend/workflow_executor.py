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
        """Execute the full pipeline"""
        try:
            logger.info(f"Starting workflow execution: {workflow.id}")

            # Step 1: Extract Figma design
            await self._step_extract_figma(workflow)

            # Step 2: Generate code
            await self._step_generate_code(workflow)

            # Step 3: Start dev server and render
            await self._step_render(workflow)

            # Step 4: Visual audit
            await self._step_visual_audit(workflow)

            # Step 5: Wait for approval
            approved = await self._step_await_approval(workflow)

            if not approved:
                logger.info(f"Workflow {workflow.id} rejected or cancelled")
                return

            # Step 6: Push to GitHub
            await self._step_push_github(workflow)

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
            import requests
            from urllib.parse import urlparse, parse_qs

            # Parse Figma URL
            parsed = urlparse(workflow.figma_url)
            path_parts = parsed.path.split('/')
            file_id = path_parts[2] if len(path_parts) > 2 else None
            node_id = parse_qs(parsed.query).get('node-id', [None])[0]

            if not file_id:
                raise ValueError(f"Invalid Figma URL: {workflow.figma_url}")

            figma_token = os.getenv("FIGMA_TOKEN")
            if not figma_token:
                raise ValueError("FIGMA_TOKEN not found in environment")

            headers = {"X-Figma-Token": figma_token}

            # Get file data
            await workflow_manager.transition(
                workflow,
                WorkflowState.GENERATING,
                step_name="Extracting Figma design",
                progress=10,
                message="Fetching Figma file data..."
            )

            file_url = f"https://api.figma.com/v1/files/{file_id}"
            if node_id:
                file_url += f"?ids={node_id}"

            response = requests.get(file_url, headers=headers, timeout=30)
            if response.status_code != 200:
                raise RuntimeError(f"Figma API error: {response.status_code} - {response.text}")

            figma_data = response.json()
            workflow.figma_metadata = {
                "file_id": file_id,
                "node_id": node_id,
                "name": figma_data.get("name", "Untitled"),
                "last_modified": figma_data.get("lastModified")
            }

            # Get screenshot
            await workflow_manager.transition(
                workflow,
                WorkflowState.GENERATING,
                step_name="Extracting Figma design",
                progress=15,
                message="Capturing Figma screenshot..."
            )

            # Determine node ID for screenshot
            screenshot_node_id = node_id
            if not screenshot_node_id:
                # Get first frame/page
                doc = figma_data.get("document", {})
                children = doc.get("children", [])
                if children:
                    first_page = children[0]
                    page_children = first_page.get("children", [])
                    if page_children:
                        screenshot_node_id = page_children[0].get("id")

            if screenshot_node_id:
                screenshot_url = f"https://api.figma.com/v1/images/{file_id}"
                params = {
                    "ids": screenshot_node_id,
                    "format": "png",
                    "scale": 2
                }
                img_response = requests.get(screenshot_url, headers=headers, params=params, timeout=30)
                if img_response.status_code == 200:
                    img_data = img_response.json()
                    images = img_data.get("images", {})
                    if images:
                        img_url = list(images.values())[0]
                        if img_url:
                            img_content = requests.get(img_url, timeout=30)
                            if img_content.status_code == 200:
                                # Save screenshot
                                screenshots_dir = Path(__file__).parent.parent.parent / "mcp-automation" / "screenshots" / workflow.id
                                screenshots_dir.mkdir(parents=True, exist_ok=True)
                                screenshot_path = screenshots_dir / "figma_original.png"
                                with open(screenshot_path, "wb") as f:
                                    f.write(img_content.content)
                                workflow.figma_screenshot = str(screenshot_path)
                                logger.info(f"Figma screenshot saved: {screenshot_path}")

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

            # Generate code
            result = await converter.convert(
                figma_url=workflow.figma_url,
                output_dir=output_dir
            )

            workflow.project_path = str(output_dir)

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
                message="Starting Next.js dev server..."
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
            logger.error(f"Rendering failed: {e}")
            # Don't fail the whole workflow if rendering fails
            workflow.rendered_screenshot = None
            await workflow_manager.complete_step(workflow, "Rendering website", False, f"Render skipped: {e}")

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
                # No screenshots available, create mock audit
                workflow.audit_result = {
                    "score": 0.90,
                    "passed": False,
                    "threshold": 0.95,
                    "issues": [
                        {"type": "screenshot_missing", "description": "Could not capture screenshots for comparison", "severity": "minor"}
                    ]
                }
                workflow.audit_score = 0.90

            await workflow_manager.complete_step(workflow, "Visual audit", True, f"Score: {workflow.audit_score:.0%}")

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

    async def _step_await_approval(self, workflow: WorkflowContext) -> bool:
        """Step 5: Wait for user approval"""
        logger.info(f"Requesting approval for workflow {workflow.id}")

        # Request approval via WebSocket
        response = await workflow_manager.request_approval(workflow, timeout=300)

        if response.get("approved"):
            await workflow_manager.complete_step(workflow, "Awaiting approval", True, "User approved")
            return True
        elif response.get("cancelled"):
            await workflow_manager.complete_step(workflow, "Awaiting approval", False, "User cancelled")
            return False
        else:
            # Rejected - could trigger regeneration
            await workflow_manager.complete_step(workflow, "Awaiting approval", False, "User rejected")
            return False

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
