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
    AWAITING_APPROVAL = "awaiting_approval"
    REGENERATING = "regenerating"
    DEPLOYING = "deploying"
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

    # Approval
    approval_status: str = "pending"  # pending, approved, rejected

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
            "project_path": self.project_path,
            "github_url": self.github_url,
            "vercel_url": self.vercel_url,
            "error": self.error,
            "total_duration": self.total_duration
        }


class WorkflowStateMachine:
    """
    Manages workflow state transitions and coordinates with WebSocket server

    State Flow:
    idle -> generating -> rendering -> auditing -> previewing
         -> awaiting_approval -> deploying -> done
                    |
                    v (if rejected)
              regenerating -> rendering -> ...
    """

    # Define valid state transitions
    VALID_TRANSITIONS = {
        WorkflowState.IDLE: [WorkflowState.GENERATING],
        WorkflowState.GENERATING: [WorkflowState.RENDERING, WorkflowState.ERROR],
        WorkflowState.RENDERING: [WorkflowState.AUDITING, WorkflowState.ERROR],
        WorkflowState.AUDITING: [WorkflowState.PREVIEWING, WorkflowState.AWAITING_APPROVAL, WorkflowState.ERROR],
        WorkflowState.PREVIEWING: [WorkflowState.AWAITING_APPROVAL],
        WorkflowState.AWAITING_APPROVAL: [WorkflowState.DEPLOYING, WorkflowState.REGENERATING, WorkflowState.CANCELLED],
        WorkflowState.REGENERATING: [WorkflowState.RENDERING, WorkflowState.ERROR],
        WorkflowState.DEPLOYING: [WorkflowState.DONE, WorkflowState.ERROR],
        WorkflowState.DONE: [],
        WorkflowState.ERROR: [WorkflowState.IDLE],  # Allow retry
        WorkflowState.CANCELLED: [WorkflowState.IDLE]
    }

    # Default workflow steps
    DEFAULT_STEPS = [
        "Extracting Figma design",
        "Generating React code",
        "Starting dev server",
        "Rendering website",
        "Visual audit",
        "Awaiting approval",
        "Creating GitHub repo",
        "Deploying to Vercel"
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
        if not self.can_transition(workflow, new_state):
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

        # Create approval request
        from websocket_server import ApprovalRequest
        approval_request = ApprovalRequest(
            workflow_id=workflow.id,
            figma_screenshot=workflow.figma_screenshot or "",
            rendered_screenshot=workflow.rendered_screenshot or "",
            diff_image=workflow.diff_image,
            audit_result=workflow.audit_result or {},
            project_path=workflow.project_path or ""
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
            WorkflowState.REGENERATING,
            WorkflowState.DEPLOYING
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
