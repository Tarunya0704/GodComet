"""
GodComet WebSocket Server
Real-time workflow progress updates and approval workflow
"""

import asyncio
import json
import logging
from typing import Dict, List, Set, Optional, Callable, Awaitable
from dataclasses import dataclass, asdict
from datetime import datetime

logger = logging.getLogger(__name__)

# Try to import websockets, provide instructions if not available
try:
    import websockets
    from websockets.exceptions import ConnectionClosed
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    ConnectionClosed = Exception  # Fallback
    logger.warning("websockets package not installed. Run: pip install websockets")


@dataclass
class WorkflowProgress:
    """Progress update for a workflow step"""
    workflow_id: str
    state: str
    step: str
    progress: int  # 0-100
    elapsed_time: float
    message: Optional[str] = None
    details: Optional[Dict] = None


@dataclass
class ApprovalRequest:
    """Request for user approval with preview data"""
    workflow_id: str
    figma_screenshot: str  # base64 or file path
    rendered_screenshot: str
    diff_image: Optional[str]
    audit_result: Dict
    project_path: str
    figma_url: str = ""  # Original Figma URL so preview can link to design


@dataclass
class CodeApprovalRequest:
    """Gate 1 — sent before GitHub push so the user can review generated code."""
    workflow_id: str
    figma_screenshot: str       # base64 data URI
    rendered_screenshot: str    # base64 data URI
    audit_score: Optional[float]
    audit_result: Dict
    project_path: str
    generated_files: List[str]  # relative paths of generated .tsx files
    figma_url: str = ""


@dataclass
class DeployApprovalRequest:
    """Gate 2 — sent after GitHub push so the user can approve/skip Vercel deploy."""
    workflow_id: str
    github_url: str
    repo_name: str
    project_path: str
    audit_score: Optional[float]


@dataclass
class WorkflowComplete:
    """Workflow completion notification"""
    workflow_id: str
    success: bool
    github_url: Optional[str]
    vercel_url: Optional[str]
    project_path: str
    final_score: float
    error: Optional[str] = None


class WorkflowWebSocketServer:
    """
    WebSocket server for real-time workflow updates

    Features:
    - Broadcast progress updates to all connected clients
    - Request approval and wait for response
    - Send completion notifications
    - Handle errors gracefully
    """

    def __init__(self):
        self.clients: Set = set()
        self.pending_approvals: Dict[str, asyncio.Future] = {}         # legacy gate
        self.pending_code_approvals: Dict[str, asyncio.Future] = {}    # Gate 1
        self.pending_deploy_approvals: Dict[str, asyncio.Future] = {}  # Gate 2
        self.server = None
        self.port = 8002

    async def start(self, port: int = 8002):
        """Start the WebSocket server"""
        if not WEBSOCKETS_AVAILABLE:
            logger.error("Cannot start WebSocket server: websockets package not installed")
            return

        self.port = port

        try:
            self.server = await websockets.serve(
                self._handle_client,
                "localhost",
                port
            )
            logger.info(f"WebSocket server started on ws://localhost:{port}")
        except Exception as e:
            logger.error(f"Failed to start WebSocket server: {e}")
            raise

    async def stop(self):
        """Stop the WebSocket server"""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            logger.info("WebSocket server stopped")

    async def _handle_client(self, websocket):
        """Handle a new client connection (websockets 12+ API - no path argument)"""
        self.clients.add(websocket)
        client_id = id(websocket)
        logger.info(f"Client connected: {client_id} (total: {len(self.clients)})")

        try:
            # Send welcome message
            await websocket.send(json.dumps({
                "type": "connected",
                "message": "Connected to GodComet workflow server",
                "client_id": client_id
            }))

            # Listen for messages from client
            async for message in websocket:
                await self._handle_message(websocket, message)

        except ConnectionClosed:
            logger.info(f"Client disconnected: {client_id}")
        except Exception as e:
            logger.error(f"Client error: {e}")
        finally:
            self.clients.discard(websocket)
            logger.info(f"Client removed: {client_id} (remaining: {len(self.clients)})")

    async def _handle_message(self, websocket, message: str):
        """Handle incoming message from client"""
        try:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "approval_response":
                await self._handle_approval_response(data)
            elif msg_type == "code_approval_response":
                await self._handle_code_approval_response(data)
            elif msg_type == "deploy_approval_response":
                await self._handle_deploy_approval_response(data)
            elif msg_type == "cancel":
                await self._handle_cancel(data)
            elif msg_type == "ping":
                await websocket.send(json.dumps({"type": "pong"}))
            else:
                logger.warning(f"Unknown message type: {msg_type}")

        except json.JSONDecodeError:
            logger.error(f"Invalid JSON message: {message}")
        except Exception as e:
            logger.error(f"Error handling message: {e}")

    async def _handle_approval_response(self, data: Dict):
        """Handle approval response from client"""
        workflow_id = data.get("workflow_id")
        approved = data.get("approved", False)

        if workflow_id in self.pending_approvals:
            future = self.pending_approvals[workflow_id]
            if not future.done():
                future.set_result({
                    "approved": approved,
                    "requested_changes": data.get("requested_changes", [])
                })
            logger.info(f"Approval response for {workflow_id}: {'approved' if approved else 'rejected'}")
        else:
            logger.warning(f"No pending approval for workflow: {workflow_id}")

    async def _handle_cancel(self, data: Dict):
        """Handle workflow cancellation — resolves whichever gate is currently waiting"""
        workflow_id = data.get("workflow_id")
        cancelled_payload = {"approved": False, "cancelled": True}

        for pending in (
            self.pending_approvals,
            self.pending_code_approvals,
            self.pending_deploy_approvals,
        ):
            if workflow_id in pending:
                future = pending[workflow_id]
                if not future.done():
                    future.set_result(cancelled_payload)

        logger.info(f"Workflow cancelled: {workflow_id}")

    async def _handle_code_approval_response(self, data: Dict):
        """Handle Gate 1 response: approved / change_requested / rejected"""
        workflow_id = data.get("workflow_id")
        if workflow_id in self.pending_code_approvals:
            future = self.pending_code_approvals[workflow_id]
            if not future.done():
                approved = data.get("approved", False)
                change_requested = data.get("change_requested", False)
                future.set_result({
                    "approved": approved,
                    "change_requested": change_requested,
                    "instruction": data.get("instruction", "") if change_requested else "",
                })
            logger.info(
                f"Code approval response for {workflow_id}: "
                f"{'approved' if data.get('approved') else 'change' if data.get('change_requested') else 'rejected'}"
            )
        else:
            logger.warning(f"No pending code approval for workflow: {workflow_id}")

    async def _handle_deploy_approval_response(self, data: Dict):
        """Handle Gate 2 response: approved / rejected"""
        workflow_id = data.get("workflow_id")
        if workflow_id in self.pending_deploy_approvals:
            future = self.pending_deploy_approvals[workflow_id]
            if not future.done():
                future.set_result({"approved": data.get("approved", False)})
            logger.info(
                f"Deploy approval response for {workflow_id}: "
                f"{'approved' if data.get('approved') else 'rejected'}"
            )
        else:
            logger.warning(f"No pending deploy approval for workflow: {workflow_id}")

    async def broadcast(self, message: Dict):
        """Broadcast message to all connected clients"""
        if not self.clients:
            return

        message_str = json.dumps(message, default=str)

        # Send to all clients, remove failed ones
        failed_clients = set()
        for client in self.clients:
            try:
                await client.send(message_str)
            except Exception as e:
                logger.error(f"Failed to send to client: {e}")
                failed_clients.add(client)

        # Remove failed clients
        self.clients -= failed_clients

    async def send_progress(self, progress: WorkflowProgress):
        """Send progress update to all clients"""
        await self.broadcast({
            "type": "progress",
            "workflow_id": progress.workflow_id,
            "data": asdict(progress)
        })

    async def request_approval(
        self,
        approval_request: ApprovalRequest,
        timeout: float = 300.0  # 5 minutes default timeout
    ) -> Dict:
        """
        Request approval from user and wait for response

        Args:
            approval_request: The approval request data
            timeout: How long to wait for approval (seconds)

        Returns:
            {"approved": bool, "requested_changes": list}
        """
        workflow_id = approval_request.workflow_id

        # Create future for approval response
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self.pending_approvals[workflow_id] = future

        try:
            # Send approval request to all clients
            await self.broadcast({
                "type": "approval_required",
                "workflow_id": workflow_id,
                "preview": asdict(approval_request)
            })

            logger.info(f"Approval requested for workflow: {workflow_id}")

            # Wait for response with timeout
            try:
                result = await asyncio.wait_for(future, timeout=timeout)
                return result
            except asyncio.TimeoutError:
                logger.warning(f"Approval timeout for workflow: {workflow_id}")
                return {
                    "approved": False,
                    "timeout": True,
                    "message": "Approval request timed out"
                }

        finally:
            # Clean up
            self.pending_approvals.pop(workflow_id, None)

    async def request_code_approval(
        self,
        request: "CodeApprovalRequest",
        timeout: float = 300.0
    ) -> Dict:
        """
        Gate 1: broadcast awaiting_code_approval and wait for the UI response.

        Expected response message from UI:
          {"type": "code_approval_response", "workflow_id": "...",
           "approved": true}
          {"type": "code_approval_response", "workflow_id": "...",
           "change_requested": true, "instruction": "make the button blue"}
          {"type": "code_approval_response", "workflow_id": "...",
           "approved": false}
        """
        workflow_id = request.workflow_id
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self.pending_code_approvals[workflow_id] = future

        try:
            await self.broadcast({
                "type": "awaiting_code_approval",
                "workflow_id": workflow_id,
                "preview": asdict(request)
            })
            logger.info(f"Code approval requested for workflow: {workflow_id}")

            try:
                return await asyncio.wait_for(future, timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(f"Code approval timeout for workflow: {workflow_id}")
                return {"approved": False, "timeout": True}
        finally:
            self.pending_code_approvals.pop(workflow_id, None)

    async def request_deploy_approval(
        self,
        request: "DeployApprovalRequest",
        timeout: float = 300.0
    ) -> Dict:
        """
        Gate 2: broadcast awaiting_deploy_approval and wait for the UI response.

        Expected response message from UI:
          {"type": "deploy_approval_response", "workflow_id": "...", "approved": true}
          {"type": "deploy_approval_response", "workflow_id": "...", "approved": false}
        """
        workflow_id = request.workflow_id
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self.pending_deploy_approvals[workflow_id] = future

        try:
            await self.broadcast({
                "type": "awaiting_deploy_approval",
                "workflow_id": workflow_id,
                "preview": asdict(request)
            })
            logger.info(f"Deploy approval requested for workflow: {workflow_id}")

            try:
                return await asyncio.wait_for(future, timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(f"Deploy approval timeout for workflow: {workflow_id}")
                return {"approved": False, "timeout": True}
        finally:
            self.pending_deploy_approvals.pop(workflow_id, None)

    async def send_complete(self, completion: WorkflowComplete):
        """Send workflow completion notification"""
        await self.broadcast({
            "type": "complete",
            "workflow_id": completion.workflow_id,
            "result": asdict(completion)
        })

    async def send_error(self, workflow_id: str, error: str, step: str, recoverable: bool = True):
        """Send error notification"""
        await self.broadcast({
            "type": "error",
            "workflow_id": workflow_id,
            "error": {
                "message": error,
                "step": step,
                "recoverable": recoverable
            }
        })


# Global instance
workflow_ws_server = WorkflowWebSocketServer()


async def get_websocket_server() -> WorkflowWebSocketServer:
    """Get the global WebSocket server instance"""
    return workflow_ws_server
