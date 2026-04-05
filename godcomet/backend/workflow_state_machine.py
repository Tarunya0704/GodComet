"""
GodComet Workflow State Machine
Manages workflow states and transitions for Figma-to-Production pipeline
"""

import asyncio
import logging
import time
import uuid
import base64
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Any
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


class WorkflowState(Enum):
    """Workflow states"""
    IDLE = "idle"
    GENERATING = "generating"
    RENDERING = "rendering"
    AUDITING = "auditing"
    PREVIEWING = "previewing"
    # Legacy single gate — kept so any existing callers don't break
    AWAITING_APPROVAL = "awaiting_approval"
    # Gate 1: user reviews generated code before GitHub push
    AWAITING_CODE_APPROVAL = "awaiting_code_approval"
    # User requested edits at Gate 1 — re-runs codegen then returns to Gate 1
    CHANGE_REQUESTED = "change_requested"
    REGENERATING = "regenerating"
    DEPLOYING = "deploying"
    # Gate 2: user approves Vercel deploy after GitHub push
    AWAITING_DEPLOY_APPROVAL = "awaiting_deploy_approval"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class WorkflowStep:
    """A single step in the workflow"""
    name: str
    status: str = "pending"  # pending, running, completed, failed
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    message: Optional[str] = None
    details: Optional[Dict] = None

    @property
    def duration(self) -> Optional[float]:
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return None


@dataclass
class WorkflowContext:
    """Complete workflow context"""
    id: str
    state: WorkflowState
    figma_url: str
    project_name: str
    created_at: datetime

    # Progress tracking
    current_step: str = ""
    progress: int = 0  # 0-100
    steps: List[WorkflowStep] = field(default_factory=list)

    # Figma extraction
    figma_screenshot: Optional[str] = None
    figma_metadata: Optional[Dict] = None

    # Code generation
    project_path: Optional[str] = None

    # Visual audit
    rendered_screenshot: Optional[str] = None
    diff_image: Optional[str] = None
    audit_result: Optional[Dict] = None
    audit_score: Optional[float] = None

    # Legacy single-gate approval
    approval_status: str = "pending"  # pending, approved, rejected

    # Gate 1 — code review before GitHub push
    code_approval_status: str = "pending"   # pending, approved, rejected, change_requested
    # Gate 2 — deploy approval before Vercel
    deploy_approval_status: str = "pending"  # pending, approved, rejected
    # Change instruction from user at Gate 1 ("make the button blue")
    change_request: Optional[str] = None

    # Component registry
    registry_path: Optional[str] = None

    # Deployment
    github_url: Optional[str] = None
    vercel_url: Optional[str] = None

    # Error handling
    error: Optional[str] = None
    error_step: Optional[str] = None

    # Timing
    start_time: Optional[float] = None
    end_time: Optional[float] = None

    @property
    def total_duration(self) -> Optional[float]:
        if self.start_time:
            end = self.end_time or time.time()
            return end - self.start_time
        return None

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        return {
            "id": self.id,
            "state": self.state.value,
            "figma_url": self.figma_url,
            "project_name": self.project_name,
            "created_at": self.created_at.isoformat(),
            "current_step": self.current_step,
            "progress": self.progress,
            "steps": [
                {
                    "name": s.name,
                    "status": s.status,
                    "duration": s.duration,
                    "message": s.message
                }
                for s in self.steps
            ],
            "figma_screenshot": self.figma_screenshot,
            "rendered_screenshot": self.rendered_screenshot,
            "audit_score": self.audit_score,
            "audit_result": self.audit_result,
            "approval_status": self.approval_status,
            "code_approval_status": self.code_approval_status,
            "deploy_approval_status": self.deploy_approval_status,
            "change_request": self.change_request,
            "project_path": self.project_path,
            "registry_path": self.registry_path,
            "github_url": self.github_url,
            "vercel_url": self.vercel_url,
            "error": self.error,
            "total_duration": self.total_duration,
            "figma_metadata": self.figma_metadata
        }


class WorkflowStateMachine:
    """
    Manages workflow state transitions and coordinates with WebSocket server

    State Flow:
    idle → generating → rendering → auditing
         → awaiting_code_approval  ← ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐
               │ approve                                      │ (loop back after change)
               │ change ──→ change_requested → generating ───┘
               │ reject ──→ error
               ↓
           deploying  (GitHub push)
               ↓
         awaiting_deploy_approval
               │ approve
               │ reject ──→ done  (kept on GitHub, not deployed)
               ↓
           deploying  (Vercel deploy)
               ↓
             done

    Legacy path (backward compat): auditing → awaiting_approval → deploying → done
    """

    # Define valid state transitions
    VALID_TRANSITIONS = {
        WorkflowState.IDLE: [WorkflowState.GENERATING],
        WorkflowState.GENERATING: [WorkflowState.GENERATING, WorkflowState.RENDERING, WorkflowState.ERROR],
        WorkflowState.RENDERING: [WorkflowState.RENDERING, WorkflowState.AUDITING, WorkflowState.ERROR],
        WorkflowState.AUDITING: [
            WorkflowState.AUDITING,
            WorkflowState.AWAITING_CODE_APPROVAL,
            WorkflowState.PREVIEWING,
            WorkflowState.AWAITING_APPROVAL,   # legacy path
            WorkflowState.ERROR,
        ],
        WorkflowState.PREVIEWING: [
            WorkflowState.AWAITING_CODE_APPROVAL,
            WorkflowState.AWAITING_APPROVAL,   # legacy path
        ],
        # Legacy single gate (kept for backward compat)
        WorkflowState.AWAITING_APPROVAL: [
            WorkflowState.DEPLOYING, WorkflowState.REGENERATING, WorkflowState.CANCELLED,
        ],
        # Gate 1: code review before GitHub push
        WorkflowState.AWAITING_CODE_APPROVAL: [
            WorkflowState.DEPLOYING,           # approved → push to GitHub
            WorkflowState.CHANGE_REQUESTED,    # user wants edits
            WorkflowState.ERROR,               # rejected
            WorkflowState.CANCELLED,
        ],
        WorkflowState.CHANGE_REQUESTED: [
            WorkflowState.GENERATING,          # re-run codegen
            WorkflowState.RENDERING,           # or jump straight to re-render
            WorkflowState.ERROR,
        ],
        WorkflowState.REGENERATING: [WorkflowState.RENDERING, WorkflowState.ERROR],
        # GitHub push happens inside DEPLOYING; then optionally pauses at Gate 2
        WorkflowState.DEPLOYING: [
            WorkflowState.DEPLOYING,
            WorkflowState.AWAITING_DEPLOY_APPROVAL,
            WorkflowState.DONE,
            WorkflowState.ERROR,
        ],
        # Gate 2: deploy approval before Vercel
        WorkflowState.AWAITING_DEPLOY_APPROVAL: [
            WorkflowState.DEPLOYING,           # approved → Vercel deploy
            WorkflowState.DONE,                # rejected → done without Vercel
            WorkflowState.CANCELLED,
        ],
        WorkflowState.DONE: [],
        WorkflowState.ERROR: [WorkflowState.IDLE],
        WorkflowState.CANCELLED: [WorkflowState.IDLE],
    }

    # Default workflow steps
    DEFAULT_STEPS = [
        "Extracting Figma design",
        "Generating React code",
        "Starting dev server",
        "Rendering website",
        "Visual audit",
        "Awaiting code approval",    # Gate 1
        "Creating GitHub repo",
        "Awaiting deploy approval",  # Gate 2
        "Deploying to Vercel",
    ]

    def __init__(self, websocket_server=None):
        """
        Initialize the state machine

        Args:
            websocket_server: WebSocket server instance for sending updates
        """
        self.workflows: Dict[str, WorkflowContext] = {}
        self.ws_server = websocket_server

    def set_websocket_server(self, ws_server):
        """Set the WebSocket server for sending updates"""
        self.ws_server = ws_server

    def create_workflow(
        self,
        figma_url: str,
        project_name: Optional[str] = None
    ) -> WorkflowContext:
        """Create a new workflow"""
        workflow_id = str(uuid.uuid4())[:8]

        if not project_name:
            project_name = f"figma-project-{workflow_id}"

        workflow = WorkflowContext(
            id=workflow_id,
            state=WorkflowState.IDLE,
            figma_url=figma_url,
            project_name=project_name,
            created_at=datetime.now(),
            steps=[WorkflowStep(name=step) for step in self.DEFAULT_STEPS]
        )

        self.workflows[workflow_id] = workflow
        logger.info(f"Created workflow: {workflow_id} for {figma_url}")

        return workflow

    def get_workflow(self, workflow_id: str) -> Optional[WorkflowContext]:
        """Get a workflow by ID"""
        return self.workflows.get(workflow_id)

    def can_transition(self, workflow: WorkflowContext, new_state: WorkflowState) -> bool:
        """Check if transition to new state is valid"""
        valid_states = self.VALID_TRANSITIONS.get(workflow.state, [])
        return new_state in valid_states

    async def transition(
        self,
        workflow: WorkflowContext,
        new_state: WorkflowState,
        step_name: Optional[str] = None,
        progress: Optional[int] = None,
        message: Optional[str] = None,
        details: Optional[Dict] = None
    ) -> bool:
        """
        Transition workflow to new state

        Args:
            workflow: The workflow context
            new_state: Target state
            step_name: Optional step name to update
            progress: Optional progress percentage (0-100)
            message: Optional status message
            details: Optional additional details

        Returns:
            True if transition was successful
        """
        # Allow same-state transitions (progress updates within a step)
        if workflow.state != new_state and not self.can_transition(workflow, new_state):
            logger.warning(
                f"Invalid transition: {workflow.state.value} -> {new_state.value} "
                f"for workflow {workflow.id}"
            )
            return False

        old_state = workflow.state
        workflow.state = new_state

        if step_name:
            workflow.current_step = step_name
            # Update step status
            for step in workflow.steps:
                if step.name == step_name:
                    step.status = "running"
                    step.start_time = time.time()
                    step.message = message
                    break

        if progress is not None:
            workflow.progress = progress

        # Track timing
        if new_state == WorkflowState.GENERATING and workflow.start_time is None:
            workflow.start_time = time.time()
        elif new_state in [WorkflowState.DONE, WorkflowState.ERROR, WorkflowState.CANCELLED]:
            workflow.end_time = time.time()

        logger.info(
            f"Workflow {workflow.id}: {old_state.value} -> {new_state.value}"
            f"{f' ({step_name})' if step_name else ''}"
        )

        # Send progress update via WebSocket
        if self.ws_server:
            from websocket_server import WorkflowProgress
            await self.ws_server.send_progress(WorkflowProgress(
                workflow_id=workflow.id,
                state=new_state.value,
                step=step_name or workflow.current_step,
                progress=workflow.progress,
                elapsed_time=workflow.total_duration or 0,
                message=message,
                details=details
            ))

        return True

    async def complete_step(
        self,
        workflow: WorkflowContext,
        step_name: str,
        success: bool = True,
        message: Optional[str] = None
    ):
        """Mark a step as completed"""
        for step in workflow.steps:
            if step.name == step_name:
                step.status = "completed" if success else "failed"
                step.end_time = time.time()
                step.message = message
                break

    async def request_approval(
        self,
        workflow: WorkflowContext,
        timeout: float = 300.0
    ) -> Dict:
        """
        Request user approval for the workflow

        Args:
            workflow: The workflow context
            timeout: Approval timeout in seconds

        Returns:
            Approval response dict
        """
        if not self.ws_server:
            logger.warning("No WebSocket server configured, auto-approving")
            return {"approved": True, "auto": True}

        # Transition to awaiting approval
        await self.transition(
            workflow,
            WorkflowState.AWAITING_APPROVAL,
            step_name="Awaiting approval",
            progress=60,
            message="Ready for review"
        )

        workflow.approval_status = "pending"

        # Create approval request - convert file paths to base64 for WebSocket transport
        from websocket_server import ApprovalRequest

        def _to_base64(filepath):
            """Convert file path to base64 data URI for preview display"""
            if not filepath:
                return ""
            if filepath.startswith("data:"):
                return filepath  # Already base64
            from pathlib import Path as P
            p = P(filepath)
            if p.exists():
                import base64 as b64
                with open(p, "rb") as f:
                    return f"data:image/png;base64,{b64.b64encode(f.read()).decode()}"
            return ""

        approval_request = ApprovalRequest(
            workflow_id=workflow.id,
            figma_screenshot=_to_base64(workflow.figma_screenshot),
            rendered_screenshot=_to_base64(workflow.rendered_screenshot),
            diff_image=_to_base64(workflow.diff_image) if workflow.diff_image else None,
            audit_result=workflow.audit_result or {},
            project_path=workflow.project_path or "",
            figma_url=workflow.figma_url or ""
        )

        # Request approval and wait
        response = await self.ws_server.request_approval(approval_request, timeout)

        if response.get("approved"):
            workflow.approval_status = "approved"
            logger.info(f"Workflow {workflow.id} approved")
        elif response.get("cancelled"):
            workflow.approval_status = "cancelled"
            await self.transition(workflow, WorkflowState.CANCELLED)
            logger.info(f"Workflow {workflow.id} cancelled")
        else:
            workflow.approval_status = "rejected"
            logger.info(f"Workflow {workflow.id} rejected")

        return response

    async def request_code_approval(
        self,
        workflow: WorkflowContext,
        timeout: float = 300.0
    ) -> Dict:
        """
        Gate 1 — pause before GitHub push.
        Returns one of:
          {"approved": True}
          {"change_requested": True, "instruction": "make the button blue"}
          {"approved": False}  (rejected or timed out)
        """
        if not self.ws_server:
            logger.warning("No WebSocket server configured, auto-approving code")
            return {"approved": True, "auto": True}

        await self.transition(
            workflow,
            WorkflowState.AWAITING_CODE_APPROVAL,
            step_name="Awaiting code approval",
            progress=62,
            message="Review generated code before pushing to GitHub"
        )
        workflow.code_approval_status = "pending"

        from websocket_server import CodeApprovalRequest

        def _to_base64(filepath):
            if not filepath:
                return ""
            if filepath.startswith("data:"):
                return filepath
            from pathlib import Path as P
            p = P(filepath)
            if p.exists():
                import base64 as b64
                with open(p, "rb") as f:
                    return f"data:image/png;base64,{b64.b64encode(f.read()).decode()}"
            return ""

        # Collect generated file list for the UI
        generated_files = []
        if workflow.project_path:
            from pathlib import Path as P
            project = P(workflow.project_path)
            for tsx in sorted(project.rglob("*.tsx")):
                generated_files.append(str(tsx.relative_to(project)))

        request = CodeApprovalRequest(
            workflow_id=workflow.id,
            figma_screenshot=_to_base64(workflow.figma_screenshot),
            rendered_screenshot=_to_base64(workflow.rendered_screenshot),
            audit_score=workflow.audit_score,
            audit_result=workflow.audit_result or {},
            project_path=workflow.project_path or "",
            generated_files=generated_files,
            figma_url=workflow.figma_url or ""
        )

        response = await self.ws_server.request_code_approval(request, timeout)

        if response.get("approved"):
            workflow.code_approval_status = "approved"
            logger.info(f"Workflow {workflow.id} code approved")
        elif response.get("change_requested"):
            workflow.code_approval_status = "change_requested"
            workflow.change_request = response.get("instruction", "")
            logger.info(f"Workflow {workflow.id} change requested: {workflow.change_request!r}")
        else:
            workflow.code_approval_status = "rejected"
            logger.info(f"Workflow {workflow.id} code rejected")

        return response

    async def request_deploy_approval(
        self,
        workflow: WorkflowContext,
        timeout: float = 300.0
    ) -> Dict:
        """
        Gate 2 — pause after GitHub push, before Vercel deploy.
        Returns one of:
          {"approved": True}
          {"approved": False}  (skipped deploy — code stays on GitHub)
        """
        if not self.ws_server:
            logger.warning("No WebSocket server configured, auto-approving deploy")
            return {"approved": True, "auto": True}

        await self.transition(
            workflow,
            WorkflowState.AWAITING_DEPLOY_APPROVAL,
            step_name="Awaiting deploy approval",
            progress=87,
            message="Code is on GitHub — approve to deploy to Vercel"
        )
        workflow.deploy_approval_status = "pending"

        from websocket_server import DeployApprovalRequest

        request = DeployApprovalRequest(
            workflow_id=workflow.id,
            github_url=workflow.github_url or "",
            repo_name=workflow.project_name,
            project_path=workflow.project_path or "",
            audit_score=workflow.audit_score
        )

        response = await self.ws_server.request_deploy_approval(request, timeout)

        if response.get("approved"):
            workflow.deploy_approval_status = "approved"
            logger.info(f"Workflow {workflow.id} deploy approved")
        else:
            workflow.deploy_approval_status = "rejected"
            logger.info(f"Workflow {workflow.id} deploy skipped — code stays on GitHub only")

        return response

    async def set_error(
        self,
        workflow: WorkflowContext,
        error: str,
        step: Optional[str] = None
    ):
        """Set workflow to error state"""
        workflow.error = error
        workflow.error_step = step or workflow.current_step

        await self.transition(
            workflow,
            WorkflowState.ERROR,
            message=error
        )

        # Send error via WebSocket
        if self.ws_server:
            await self.ws_server.send_error(
                workflow.id,
                error,
                workflow.error_step or "unknown",
                recoverable=True
            )

    async def complete_workflow(
        self,
        workflow: WorkflowContext,
        github_url: Optional[str] = None,
        vercel_url: Optional[str] = None
    ):
        """Mark workflow as complete"""
        workflow.github_url = github_url
        workflow.vercel_url = vercel_url

        await self.transition(
            workflow,
            WorkflowState.DONE,
            step_name="Complete",
            progress=100,
            message="Deployment successful!"
        )

        # Complete all remaining steps
        for step in workflow.steps:
            if step.status == "pending":
                step.status = "skipped"

        # Send completion via WebSocket
        if self.ws_server:
            from websocket_server import WorkflowComplete
            await self.ws_server.send_complete(WorkflowComplete(
                workflow_id=workflow.id,
                success=True,
                github_url=github_url,
                vercel_url=vercel_url,
                project_path=workflow.project_path or "",
                final_score=workflow.audit_score or 0.0
            ))

    def get_all_workflows(self) -> List[Dict]:
        """Get all workflows as dictionaries"""
        return [w.to_dict() for w in self.workflows.values()]

    def get_active_workflows(self) -> List[Dict]:
        """Get workflows that are not done/error/cancelled"""
        active_states = [
            WorkflowState.GENERATING,
            WorkflowState.RENDERING,
            WorkflowState.AUDITING,
            WorkflowState.PREVIEWING,
            WorkflowState.AWAITING_APPROVAL,
            WorkflowState.AWAITING_CODE_APPROVAL,
            WorkflowState.AWAITING_DEPLOY_APPROVAL,
            WorkflowState.CHANGE_REQUESTED,
            WorkflowState.REGENERATING,
            WorkflowState.DEPLOYING,
        ]
        return [
            w.to_dict() for w in self.workflows.values()
            if w.state in active_states
        ]


# Global instance
workflow_manager = WorkflowStateMachine()


def get_workflow_manager() -> WorkflowStateMachine:
    """Get the global workflow manager instance"""
    return workflow_manager
