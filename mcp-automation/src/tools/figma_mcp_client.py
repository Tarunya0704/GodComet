"""
Figma MCP Client — HTTP transport
==================================
Starts figma-developer-mcp as a local HTTP server (one persistent process),
then calls its tools via plain HTTP POST JSON-RPC requests.

Advantages over stdio transport on Windows:
  • No subprocess stdin/stdout buffering issues
  • Server stays alive between calls (faster subsequent calls)
  • Standard HTTP — no asyncio subprocess pipe gymnastics

Usage:
    client = FigmaMCPClient(figma_token)
    data   = await client.get_design_data("FILE_KEY")
    await client.stop()   # or use as async context manager

Setup (one-time, automatic via npx):
    npx figma-developer-mcp --port 3333 --figma-api-key=TOKEN
"""

import asyncio
import json
import logging
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

DEFAULT_PORT       = 3333
HEALTH_POLL_SEC    = 0.5
HEALTH_TIMEOUT_SEC = 30        # max wait for server to become ready (Windows is slow)
TOOL_TIMEOUT_SEC   = 30        # per-tool-call HTTP timeout


# ── Helpers ───────────────────────────────────────────────────────────────────

def _port_in_use(port: int) -> bool:
    """Return True if something is already listening on the port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _find_free_port(start: int = DEFAULT_PORT, attempts: int = 20) -> int:
    """Return the first free TCP port at or after *start*."""
    for port in range(start, start + attempts):
        if not _port_in_use(port):
            return port
    raise RuntimeError(f"No free port found in range {start}–{start + attempts}")


def _npx() -> str:
    npx = shutil.which("npx")
    if not npx:
        raise RuntimeError(
            "npx not found — install Node.js from https://nodejs.org and retry."
        )
    return npx


# ── Client ────────────────────────────────────────────────────────────────────

class FigmaMCPClient:
    """
    HTTP-transport client for figma-developer-mcp.

    The MCP server is started as a background subprocess once in __init__
    and reused for all subsequent tool calls.  Call stop() (or use the async
    context manager) to terminate the server when done.
    """

    def __init__(self, figma_token: str, port: int = 0):
        """
        Parameters
        ----------
        figma_token : str
            Figma personal access token.
        port : int
            Port to bind the HTTP server to.  0 = auto-select a free port.
        """
        if not figma_token:
            raise ValueError("figma_token must not be empty")

        self.figma_token  = figma_token.strip()
        self._proc: Optional[subprocess.Popen] = None
        self._ready       = False
        self._port        = port if port else DEFAULT_PORT
        self._base_url    = f"http://127.0.0.1:{self._port}"
        # StreamableHTTP MCP endpoint (server logs: "StreamableHTTP endpoint available at .../mcp")
        self._mcp_url     = f"http://127.0.0.1:{self._port}/mcp"

        self._owned = False  # True only if THIS client spawned the process

        if _port_in_use(self._port):
            # An MCP server is already listening — reuse it, skip Popen
            logger.info(
                "MCP server already running on port %d — reusing existing instance",
                self._port,
            )
            self._ready = True
        else:
            _npx()  # raise early if Node.js missing
            self._start_server()
            self._owned = True

    # ── Server lifecycle ──────────────────────────────────────────────────────

    def _start_server(self) -> None:
        """Start the MCP HTTP server as a background subprocess."""
        env = {
            **os.environ,
            "FIGMA_API_KEY": self.figma_token,
        }

        cmd = (
            f'npx --yes figma-developer-mcp '
            f'--port {self._port} '
            f'--figma-api-key={self.figma_token}'
        )

        kwargs: Dict[str, Any] = dict(
            shell=True,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Windows: suppress the console window that would otherwise flash up
        if platform.system() == "Windows":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        self._proc = subprocess.Popen(cmd, **kwargs)
        logger.info(
            "MCP server starting on port %d (pid=%d)", self._port, self._proc.pid
        )

    async def _wait_ready(self) -> None:
        """
        Poll the server until it accepts connections or the timeout expires.

        Strategy: GET / — any response code (even 404/405) means the HTTP
        server is up and accepting connections.  A connection-refused error
        means it isn't ready yet.
        """
        deadline = time.monotonic() + HEALTH_TIMEOUT_SEC
        attempt  = 0

        async with aiohttp.ClientSession() as session:
            while time.monotonic() < deadline:
                attempt += 1

                # If the process already died, bail immediately
                if self._proc and self._proc.poll() is not None:
                    stderr = b""
                    try:
                        stderr = self._proc.stderr.read(500)
                    except Exception:
                        pass
                    raise RuntimeError(
                        f"MCP server process exited before becoming ready. "
                        f"stderr: {stderr.decode(errors='replace').strip()}"
                    )

                try:
                    # Poll /mcp — the StreamableHTTP endpoint the server exposes.
                    # Any HTTP response (even 4xx) means the server is listening.
                    async with session.get(
                        self._mcp_url,
                        timeout=aiohttp.ClientTimeout(total=1),
                    ) as resp:
                        logger.info(
                            "MCP server ready on port %d (attempt %d, status %d)",
                            self._port, attempt, resp.status,
                        )
                        self._ready = True
                        return
                except (aiohttp.ClientConnectorError, aiohttp.ServerDisconnectedError):
                    pass  # not ready yet
                except Exception as e:
                    logger.debug("Health poll error (attempt %d): %s", attempt, e)

                await asyncio.sleep(HEALTH_POLL_SEC)

        raise RuntimeError(
            f"MCP HTTP server did not become ready within {HEALTH_TIMEOUT_SEC}s "
            f"on port {self._port}"
        )

    def stop(self) -> None:
        """Terminate the background MCP server process.

        Only terminates if this client instance actually spawned the process
        (_owned=True).  Clients that reused an existing server on the port
        will not kill it.
        """
        if not self._owned:
            # This client attached to an already-running server — don't kill it
            self._ready = False
            return
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc  = None
        self._ready = False
        logger.info("MCP server stopped")

    def __del__(self):
        try:
            self.stop()
        except Exception:
            pass

    # ── Async context manager ─────────────────────────────────────────────────

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        self.stop()

    # ── HTTP transport ────────────────────────────────────────────────────────

    async def _call_tools(self, tool_calls: List[Dict]) -> List[Dict]:
        """
        Ensure the server is ready then POST each tool call as a JSON-RPC
        request to the HTTP server.  Returns a list of result dicts in the
        same order as *tool_calls*.
        """
        if not self._ready:
            await self._wait_ready()

        results: List[Dict] = []
        # The /mcp endpoint returns text/event-stream (SSE) responses.
        # Each response is one or more "data: <json>\n\n" lines.
        req_headers = {
            "Content-Type": "application/json",
            "Accept":       "application/json, text/event-stream",
        }

        async with aiohttp.ClientSession(headers=req_headers) as session:
            # ── MCP handshake (initialize) ────────────────────────────────────
            init_payload = {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "godcomet-figma-client", "version": "1.0.0"},
                },
            }
            session_id: Optional[str] = None
            async with session.post(
                self._mcp_url, json=init_payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                # Capture the session ID returned by the server — required for
                # all subsequent requests in this MCP session.
                session_id = resp.headers.get("mcp-session-id")
                if session_id:
                    logger.debug("MCP session ID: %s", session_id)
                init_body = self._parse_sse(await resp.text())
                if "error" in init_body:
                    raise RuntimeError(f"MCP init error: {init_body['error']}")
                logger.debug(
                    "MCP handshake OK: protocol=%s",
                    init_body.get("result", {}).get("protocolVersion", "?"),
                )

            # Build headers for all subsequent requests (include session ID if present)
            session_headers = {"mcp-session-id": session_id} if session_id else {}

            # notifications/initialized — server may return empty 202, ignore errors
            notif = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
            try:
                async with session.post(
                    self._mcp_url, json=notif, timeout=aiohttp.ClientTimeout(total=5),
                    headers=session_headers,
                ) as _:
                    pass
            except Exception:
                pass

            # ── Execute tool calls ────────────────────────────────────────────
            for call in tool_calls:
                payload = {
                    "jsonrpc": "2.0",
                    "id":      call.get("id", len(results) + 1),
                    "method":  call["method"],
                    "params":  call["params"],
                }

                try:
                    async with session.post(
                        self._mcp_url, json=payload,
                        timeout=aiohttp.ClientTimeout(total=TOOL_TIMEOUT_SEC),
                        headers=session_headers,
                    ) as resp:
                        body = self._parse_sse(await resp.text())

                    if "error" in body:
                        logger.warning(
                            "MCP tool error (id=%s): %s", payload["id"], body["error"],
                        )
                        results.append({"error": body["error"]})
                    else:
                        results.append(body.get("result", {}))

                except asyncio.TimeoutError:
                    logger.error(
                        "MCP tool call timed out after %ds (id=%s)",
                        TOOL_TIMEOUT_SEC, payload["id"],
                    )
                    raise
                except Exception as e:
                    logger.error("MCP HTTP call failed: %s", e)
                    raise

        return results

    def _parse_sse(self, text: str) -> Dict:
        """
        Parse a Server-Sent Events response body into a JSON dict.

        The /mcp endpoint returns SSE format:
            event: message
            data: {"jsonrpc":"2.0","id":0,"result":{...}}

        Finds the first 'data:' line and JSON-decodes it.
        Falls back to direct JSON parse if the body isn't SSE.
        """
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                payload = line[5:].strip()
                if payload:
                    try:
                        return json.loads(payload)
                    except json.JSONDecodeError:
                        pass
        # Fallback: maybe it's plain JSON (future server versions)
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            if text.strip():
                logger.warning("Unparseable MCP response: %s", text[:200])
            return {}

    # ── Parse helper ──────────────────────────────────────────────────────────

    def _parse_mcp_response(self, response: Any) -> Dict:
        """
        Normalise a raw MCP result into a plain dict.

        MCP tool results are returned as:
          {"content": [{"type": "text", "text": "<json-string>"}]}
        or as a direct dict.  Handles both forms and JSON embedded in text.
        """
        if isinstance(response, dict) and "error" in response:
            return {"error": response["error"]}

        content = response if isinstance(response, dict) else {}
        items   = content.get("content", [])

        if not items:
            return content  # already a plain dict result

        text_parts: List[str] = []
        for item in items:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))

        combined = "\n".join(text_parts).strip()

        if not combined:
            return {}

        # Try JSON first
        try:
            return json.loads(combined)
        except json.JSONDecodeError:
            pass

        # Fallback: try YAML (Figma MCP server may return YAML-formatted data)
        try:
            import yaml  # pyyaml
            parsed = yaml.safe_load(combined)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        logger.warning(
            "MCP response is not JSON or YAML (first 400 chars): %s", combined[:400]
        )
        return {"raw": combined}

    # ── Public API ────────────────────────────────────────────────────────────

    async def get_design_data(
        self, file_id: str, node_id: Optional[str] = None
    ) -> Dict:
        """
        Fetch design data for a Figma file (or a specific node within it).

        Returns
        -------
        dict:
            file       — full file metadata + document tree
            components — component definitions
        """
        args: Dict = {"fileKey": file_id}
        if node_id:
            args["nodeId"] = node_id

        raw = await self._call_tools([{
            "method": "tools/call",
            "params": {"name": "get_figma_data", "arguments": args},
            "id": 1,
        }])

        file_data = self._parse_mcp_response(raw[0]) if raw else {}
        return {
            "file":       file_data,
            "components": file_data.get("components", {}),
        }

    async def get_component_properties(self, file_id: str, node_id: str) -> Dict:
        """
        Return component properties, variants, and children for *node_id*.

        Returns
        -------
        dict:
            name     — component name
            props    — componentPropertyDefinitions
            variants — {prop: [values]}
            styles   — applied style IDs
            children — list of {id, name, type} for direct children
        """
        raw = await self._call_tools([{
            "method": "tools/call",
            "params": {
                "name":      "get_figma_data",
                "arguments": {"fileKey": file_id, "nodeId": node_id},
            },
            "id": 1,
        }])

        node_data  = self._parse_mcp_response(raw[0]) if raw else {}
        prop_defs: Dict = node_data.get("componentPropertyDefinitions", {})

        variants: Dict[str, List[str]] = {
            k: v.get("variantOptions", [])
            for k, v in prop_defs.items()
            if v.get("type") == "VARIANT"
        }

        children = [
            {"id": c.get("id"), "name": c.get("name"), "type": c.get("type")}
            for c in node_data.get("children", [])
        ]

        return {
            "name":     node_data.get("name", ""),
            "props":    prop_defs,
            "variants": variants,
            "styles":   node_data.get("styles", {}),
            "children": children,
        }

    async def get_local_variables(self, file_id: str) -> Dict:
        """
        Fetch Figma Variables (design tokens) from the file.

        figma-developer-mcp has no dedicated variables tool; variables are
        parsed from the full file response where available.

        Returns
        -------
        dict:
            colors     — {name: hex_or_rgba}
            spacing    — {name: float_px}
            typography — {}  (populated when MCP exposes text-style vars)
            raw        — full response for advanced use
        """
        raw = await self._call_tools([{
            "method": "tools/call",
            "params": {
                "name":      "get_figma_data",
                "arguments": {"fileKey": file_id},
            },
            "id": 1,
        }])

        data: Dict = self._parse_mcp_response(raw[0]) if raw else {}

        # Variables may live under "variables" or "localVariables"
        variables: Dict = data.get("variables") or data.get("localVariables") or {}

        colors:     Dict[str, str]   = {}
        spacing:    Dict[str, float] = {}
        typography: Dict[str, Dict]  = {}

        for var_id, var in variables.items():
            resolved = var.get("resolvedType", "")
            name     = var.get("name", var_id)
            modes    = var.get("valuesByMode", {})
            value    = next(iter(modes.values()), None)

            if value is None:
                continue

            if resolved == "COLOR" and isinstance(value, dict):
                r = round(value.get("r", 0) * 255)
                g = round(value.get("g", 0) * 255)
                b = round(value.get("b", 0) * 255)
                a = value.get("a", 1.0)
                colors[name] = (
                    f"rgba({r},{g},{b},{a:.2f})" if a < 1 else f"#{r:02x}{g:02x}{b:02x}"
                )

            elif resolved == "FLOAT" and isinstance(value, (int, float)):
                spacing[name] = float(value)

        return {
            "colors":     colors,
            "spacing":    spacing,
            "typography": typography,
            "raw":        data,
        }


# ── CLI smoke-test ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG, stream=sys.stderr,
        format="%(levelname)s %(name)s: %(message)s",
    )

    token = os.getenv("FIGMA_TOKEN", "")
    if not token:
        print("ERROR: set FIGMA_TOKEN environment variable", file=sys.stderr)
        sys.exit(1)

    file_id = sys.argv[1] if len(sys.argv) > 1 else "YOUR_FILE_ID"
    node_id = sys.argv[2] if len(sys.argv) > 2 else None

    async def _main():
        async with FigmaMCPClient(token) as client:
            print(f"\n── get_design_data({file_id!r}, node_id={node_id!r}) ──")
            result = await client.get_design_data(file_id, node_id)
            print(json.dumps(result, indent=2, default=str))

            if node_id:
                print(f"\n── get_component_properties({file_id!r}, {node_id!r}) ──")
                props = await client.get_component_properties(file_id, node_id)
                print(json.dumps(props, indent=2, default=str))

            print(f"\n── get_local_variables({file_id!r}) ──")
            variables = await client.get_local_variables(file_id)
            print(json.dumps(variables, indent=2, default=str))

    asyncio.run(_main())
