"""
GodComet Backend - Connects Electron to MCP Automation
WITH FULL CONTEXT AWARENESS + Code Analysis + Web Scraping + Real-time Workflows
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import sys
from pathlib import Path
import os
import asyncio
from dotenv import load_dotenv
import logging

# Import workflow components
from websocket_server import workflow_ws_server, WorkflowProgress
from workflow_state_machine import workflow_manager, WorkflowState
from workflow_executor import workflow_executor

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables from mcp-automation/.env (where the tokens are)
mcp_env_path = Path(__file__).parent.parent.parent / "mcp-automation" / ".env"
load_dotenv(dotenv_path=mcp_env_path)
logger.info(f"🔑 Loading environment from: {mcp_env_path}")

# Also try local .env as fallback
load_dotenv()

# Add mcp-automation/src to path
mcp_src = Path(__file__).parent.parent.parent / "mcp-automation" / "src"
sys.path.insert(0, str(mcp_src))

logger.info(f"Looking for MCP automation at: {mcp_src}")

# Import MCP components
try:
    import mcp_server
    import ai_client
    import config
    
    MCPServer = mcp_server.MCPServer
    AIClient = ai_client.AIClient
    Config = config.Config
    
    logger.info("✅ MCP components imported successfully")
except ImportError as e:
    logger.error(f"❌ Failed to import MCP components: {e}")
    logger.error(f"Make sure mcp-automation/src exists at: {mcp_src}")
    raise

# Initialize FastAPI
app = FastAPI(
    title="GodComet Backend",
    description="AI Automation Backend powered by MCP with Context Awareness, Code Analysis, and Web Scraping",
    version="2.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global instances
mcp_server_instance: MCPServer = None
ai_client_instance: AIClient = None

class CommandRequest(BaseModel):
    command: str
    context: dict = {}


class WorkflowRequest(BaseModel):
    """Request to start a Figma-to-production workflow"""
    figma_url: str
    project_name: Optional[str] = None
    frame_id: Optional[str] = None  # specific frame to convert (node-id)


class ApprovalRequest(BaseModel):
    """Approval or rejection of a workflow"""
    approved: bool
    requested_changes: Optional[List[str]] = None

@app.on_event("startup")
async def startup():
    """Initialize MCP server and AI client with all features"""
    global mcp_server_instance, ai_client_instance
    
    logger.info("=" * 60)
    logger.info("🚀 Starting GodComet Backend with Full Context Awareness")
    logger.info("=" * 60)
    
    try:
        # Validate config
        Config.validate()
        logger.info("✅ Configuration validated")
        
        # Initialize MCP Server
        logger.info("🔧 Initializing MCP server...")
        mcp_server_instance = MCPServer()
        
        # Configure integrations
        if Config.is_aws_configured():
            mcp_server_instance.configure_aws(
                Config.AWS_ACCESS_KEY_ID,
                Config.AWS_SECRET_ACCESS_KEY,
                Config.AWS_REGION
            )
            logger.info("✅ AWS configured")
        else:
            logger.info("⚠️  AWS not configured (optional)")
        
        if Config.is_jira_configured():
            mcp_server_instance.configure_jira(
                Config.JIRA_URL,
                Config.JIRA_EMAIL,
                Config.JIRA_API_TOKEN
            )
            logger.info("✅ Jira configured")
        else:
            logger.info("⚠️  Jira not configured (optional)")
        
        if Config.is_github_configured():
            mcp_server_instance.configure_github(Config.GITHUB_TOKEN)
            logger.info("✅ GitHub configured")
        else:
            logger.info("⚠️  GitHub not configured (optional)")
        
        if Config.is_vercel_configured():
            mcp_server_instance.configure_vercel(Config.VERCEL_TOKEN)
            logger.info("✅ Vercel configured")
        else:
            logger.info("⚠️  Vercel not configured (optional)")
        
        # Figma token check
        if hasattr(Config, 'FIGMA_TOKEN') and Config.FIGMA_TOKEN:
            logger.info("✅ Figma token available")
        else:
            logger.info("⚠️  Figma token not configured (optional)")
        
        # Initialize AI client
        logger.info("⚡ Initializing AI client with Groq...")
        ai_client_instance = AIClient(Config.GROQ_API_KEY, mcp_server_instance)
        
        # ⭐ NEW: Configure Code Analysis and Web Scraper Tools
        logger.info("🔧 Configuring advanced tools...")
        mcp_server_instance.configure_code_analysis(ai_client_instance)
        mcp_server_instance.configure_web_scraper(ai_client_instance)
        logger.info("✅ Code analysis and web scraper configured")
        
        # Configure Document Generator
        mcp_server_instance.configure_document_generator(ai_client_instance)
        logger.info("✅ Document generator configured")
        
        # Get final tool count
        tools = await mcp_server_instance.get_tools_list()
        tool_count = len(tools)
        
        logger.info("=" * 60)
        logger.info(f"✅ Backend ready with {tool_count} tools!")
        logger.info("=" * 60)
        logger.info("📋 Available Features:")
        logger.info("   • Context-aware command execution")
        logger.info("   • Code analysis (bugs, tests, refactoring, docs)")
        logger.info("   • Web scraping (articles, tables, competitor research)")
        logger.info("   • GitHub & Vercel integration")
        logger.info("   • Document & presentation generation")
        logger.info("   • Workflow automation")
        logger.info("   • Browser automation")
        logger.info("   • Real-time workflow updates (WebSocket)")
        logger.info("=" * 60)

        # Start WebSocket server for real-time workflow updates
        logger.info("🔌 Starting WebSocket server on port 8002...")
        asyncio.create_task(workflow_ws_server.start(port=8002))

        # Connect workflow manager to WebSocket server
        workflow_manager.set_websocket_server(workflow_ws_server)
        logger.info("✅ WebSocket server started for real-time updates")

    except Exception as e:
        logger.error(f"❌ Startup failed: {e}", exc_info=True)
        raise

@app.get("/")
async def root():
    """Health check"""
    return {
        "status": "ok",
        "service": "GodComet Backend",
        "version": "2.0.0",
        "features": {
            "context_aware": True,
            "code_analysis": True,
            "web_scraping": True,
            "workflow_engine": True,
            "document_generation": True
        }
    }

@app.get("/health")
async def health():
    """Detailed health check"""
    tools_count = 0
    if mcp_server_instance:
        try:
            tools = await mcp_server_instance.get_tools_list()
            tools_count = len(tools)
        except:
            pass
    
    return {
        "status": "ok",
        "mcp_initialized": mcp_server_instance is not None,
        "ai_initialized": ai_client_instance is not None,
        "tools_count": tools_count,
        "features": {
            "context_aware": True,
            "code_analysis": mcp_server_instance.code_analysis is not None if mcp_server_instance else False,
            "web_scraping": mcp_server_instance.web_scraper is not None if mcp_server_instance else False,
            "workflow_engine": mcp_server_instance.workflow_engine is not None if mcp_server_instance else False,
            "document_generation": mcp_server_instance.doc_gen is not None if mcp_server_instance else False
        }
    }

@app.post("/execute")
async def execute_command(request: CommandRequest):
    """Execute command using AI and MCP tools - WITH FULL CONTEXT!"""
    if not ai_client_instance or not mcp_server_instance:
        raise HTTPException(status_code=503, detail="Backend not initialized")
    
    try:
        logger.info("=" * 60)
        logger.info(f"📥 Received command: {request.command}")
        logger.info(f"📍 Context received:")
        logger.info(f"   App: {request.context.get('app', 'Unknown')}")
        logger.info(f"   File: {request.context.get('file', 'None')}")
        logger.info(f"   Window: {request.context.get('window', 'None')}")
        logger.info(f"   URL: {request.context.get('url', 'None')}")
        if request.context.get('selectedText'):
            logger.info(f"   Selected Text: {request.context.get('selectedText')[:100]}...")
        logger.info("=" * 60)
        
        # ⭐ PASS CONTEXT TO AI CLIENT
        result = await ai_client_instance.execute(
            request.command,
            context=request.context
        )
        
        logger.info(f"📤 Execution result: {'Success' if result.get('success') else 'Failed'}")
        
        if result["success"]:
            return {
                "success": True,
                "message": result['result']['message'],
                "data": result['result'].get('data'),
                "actions": result['result'].get('actions', []),
                "executionTime": result.get('execution_time', 0)
            }
        else:
            return {
                "success": False,
                "message": "Command failed",
                "error": result.get('error', 'Unknown error')
            }
            
    except Exception as e:
        logger.error(f"❌ Execution failed: {e}", exc_info=True)
        return {
            "success": False,
            "message": "Execution failed",
            "error": str(e)
        }

@app.get("/tools")
async def get_tools():
    """Get available MCP tools"""
    if not mcp_server_instance:
        raise HTTPException(status_code=503, detail="Backend not initialized")
    
    try:
        tools = await mcp_server_instance.get_tools_list()
        
        # Categorize tools
        tool_categories = {
            "browser": [],
            "code_analysis": [],
            "web_scraping": [],
            "github": [],
            "vercel": [],
            "file_system": [],
            "workflows": [],
            "documents": [],
            "jira": [],
            "aws": [],
            "other": []
        }
        
        for tool in tools:
            name = tool.name
            if name.startswith("browser_") or name == "youtube_play":
                tool_categories["browser"].append(name)
            elif name in ["analyze_code", "fix_bugs", "generate_tests", "refactor_code", "document_code"]:
                tool_categories["code_analysis"].append(name)
            elif name in ["summarize_article", "scrape_table_to_csv", "research_competitors"]:
                tool_categories["web_scraping"].append(name)
            elif name.startswith("github_"):
                tool_categories["github"].append(name)
            elif name.startswith("vercel_"):
                tool_categories["vercel"].append(name)
            elif name.startswith("file_") or name == "list_directory":
                tool_categories["file_system"].append(name)
            elif name in ["execute_workflow", "list_workflows"]:
                tool_categories["workflows"].append(name)
            elif name == "create_document_and_presentation" or name == "figma_to_website":
                tool_categories["documents"].append(name)
            elif name.startswith("jira_"):
                tool_categories["jira"].append(name)
            elif name.startswith("aws_"):
                tool_categories["aws"].append(name)
            else:
                tool_categories["other"].append(name)
        
        return {
            "total_count": len(tools),
            "tools": [tool.name for tool in tools],
            "categories": tool_categories
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/integrations")
async def get_integrations():
    """Get integration status"""
    return {
        "aws": {
            "enabled": Config.is_aws_configured(),
            "description": "Cloud storage and services"
        },
        "jira": {
            "enabled": Config.is_jira_configured(),
            "description": "Project management and issue tracking"
        },
        "github": {
            "enabled": Config.is_github_configured(),
            "description": "Code repositories and version control"
        },
        "vercel": {
            "enabled": Config.is_vercel_configured(),
            "description": "Website deployment and hosting"
        },
        "figma": {
            "enabled": hasattr(Config, 'FIGMA_TOKEN') and Config.FIGMA_TOKEN is not None,
            "description": "Design to code conversion"
        },
        "groq": {
            "enabled": hasattr(Config, 'GROQ_API_KEY') and Config.GROQ_API_KEY is not None,
            "description": "AI language model for automation"
        }
    }

@app.get("/features")
async def get_features():
    """Get available feature details"""
    if not mcp_server_instance:
        raise HTTPException(status_code=503, detail="Backend not initialized")
    
    return {
        "code_analysis": {
            "enabled": mcp_server_instance.code_analysis is not None,
            "tools": [
                "analyze_code - Find bugs and quality issues",
                "fix_bugs - Get bug fix suggestions",
                "generate_tests - Create unit tests",
                "refactor_code - Improve code quality",
                "document_code - Generate documentation"
            ]
        },
        "web_scraping": {
            "enabled": mcp_server_instance.web_scraper is not None,
            "tools": [
                "summarize_article - Extract and summarize articles",
                "scrape_table_to_csv - Export tables to CSV",
                "research_competitors - Analyze competitor websites"
            ]
        },
        "workflow_automation": {
            "enabled": mcp_server_instance.workflow_engine is not None,
            "tools": [
                "execute_workflow - Run multi-step workflows",
                "list_workflows - Show available workflows"
            ]
        },
        "document_generation": {
            "enabled": mcp_server_instance.doc_gen is not None,
            "tools": [
                "create_document_and_presentation - Generate Word docs and PowerPoint"
            ]
        },
        "context_awareness": {
            "enabled": True,
            "capabilities": [
                "Detect current file in VS Code",
                "Detect current URL in browser",
                "Detect active application",
                "Use context in commands automatically"
            ]
        }
    }

# =============================================================================
# WORKFLOW ENDPOINTS - Real-time Figma-to-Production Pipeline
# =============================================================================

class FramesRequest(BaseModel):
    figma_url: str


@app.post("/workflow/frames")
async def list_frames(request: FramesRequest):
    """Return all top-level frames in a Figma file for the user to choose from."""
    file_id = _parse_file_id(request.figma_url)
    figma_token = os.getenv("FIGMA_TOKEN", "").strip()
    if not figma_token:
        raise HTTPException(status_code=500, detail="FIGMA_TOKEN not configured")

    figma_data = _load_figma_data(file_id, figma_token)

    frames = []
    doc = figma_data.get("document", {})
    for page in doc.get("children", []):
        for child in page.get("children", []):
            if child.get("type") == "FRAME" and child.get("visible", True) is not False:
                bb = child.get("absoluteBoundingBox", {})
                frames.append({
                    "id": child.get("id", ""),
                    "name": child.get("name", "Untitled"),
                    "width": int(bb.get("width", child.get("size", {}).get("x", 0))),
                    "height": int(bb.get("height", child.get("size", {}).get("y", 0))),
                    "page": page.get("name", ""),
                })

    return {"frames": frames, "file_name": figma_data.get("name", "")}


# ---------------------------------------------------------------------------
# Shared helpers for section endpoints
# ---------------------------------------------------------------------------

def _load_figma_data(file_id: str, figma_token: str) -> dict:
    """Load Figma file from 1-hour disk cache or live API. Raises HTTPException."""
    import json as _j, time as _t, requests as _r
    cache_dir = Path(__file__).parent.parent.parent / "mcp-automation" / "figma_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{file_id}.json"
    if cache_file.exists() and (_t.time() - cache_file.stat().st_mtime) < 3600:
        try:
            return _j.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    resp = _r.get(
        f"https://api.figma.com/v1/files/{file_id}",
        headers={"X-Figma-Token": figma_token},
        timeout=30,
    )
    if resp.status_code == 429:
        raise HTTPException(status_code=429, detail="Figma rate limit — try again shortly")
    if resp.status_code == 403:
        raise HTTPException(status_code=403, detail="Figma 403 — check FIGMA_TOKEN")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Figma API {resp.status_code}")
    data = resp.json()
    cache_file.write_text(_j.dumps(data), encoding="utf-8")
    return data


def _find_node_by_id(node, target_id: str):
    """Walk a FigmaNode tree and return the node whose id matches target_id.
    Normalises both to colon format so URL hyphens (1-514) match API colons (1:514)."""
    norm = target_id.replace("-", ":").replace("_", ":")
    if (node.id or "").replace("-", ":").replace("_", ":") == norm:
        return node
    for child in node.children:
        found = _find_node_by_id(child, target_id)
        if found:
            return found
    return None


def _parse_file_id(figma_url: str) -> str:
    import re as _re
    m = _re.search(r'/(?:design|file)/([a-zA-Z0-9]+)', figma_url)
    if not m:
        raise HTTPException(status_code=400, detail="Cannot extract file_id from Figma URL")
    return m.group(1)


def _frame_screenshot_path(file_id: str, frame_id: str) -> Optional[Path]:
    """Return path to cached frame screenshot, or None if not yet rendered."""
    safe = frame_id.replace(":", "_").replace("-", "_").replace(";", "_")
    p = (
        Path(__file__).parent.parent.parent
        / "mcp-automation" / "image_cache" / file_id / f"frame_{safe}.png"
    )
    return p if p.exists() and p.stat().st_size > 10_000 else None


def _crop_to_b64(img, crop_box) -> Optional[str]:
    """Crop a PIL image to crop_box (x,y,w,h), scale to ≤512px wide, return data URI."""
    try:
        import base64 as _b64, io as _io
        x, y, w, h = crop_box
        region = img.crop((x, y, x + w, y + h))
        if region.width > 512:
            scale = 512 / region.width
            region = region.resize(
                (512, max(1, int(region.height * scale))),
                resample=2,  # LANCZOS
            )
        buf = _io.BytesIO()
        region.save(buf, format="PNG", optimize=True)
        return "data:image/png;base64," + _b64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# POST /workflow/sections
# ---------------------------------------------------------------------------

class SectionsRequest(BaseModel):
    figma_url: str
    frame_id: str


@app.post("/workflow/sections")
async def list_sections(request: SectionsRequest):
    """Decompose a Figma frame into semantic components and return them with thumbnail crops."""
    file_id = _parse_file_id(request.figma_url)
    figma_token = os.getenv("FIGMA_TOKEN", "").strip()
    if not figma_token:
        raise HTTPException(status_code=500, detail="FIGMA_TOKEN not configured")

    figma_data = _load_figma_data(file_id, figma_token)

    # Build FigmaNode tree
    try:
        from tools.production_figma_converter import FigmaNode
        from tools.component_decomposer import ComponentDecomposer
    except ImportError:
        from production_figma_converter import FigmaNode
        from component_decomposer import ComponentDecomposer

    root = FigmaNode(figma_data.get("document", {}))
    frame = _find_node_by_id(root, request.frame_id)
    if frame is None:
        raise HTTPException(status_code=404, detail=f"Frame {request.frame_id!r} not found in file")

    specs = ComponentDecomposer().decompose(frame)

    # Load frame screenshot for thumbnails (optional — graceful if missing)
    frame_img = None
    frame_path = _frame_screenshot_path(file_id, request.frame_id)
    if frame_path:
        try:
            from PIL import Image as _PILImage
            frame_img = _PILImage.open(str(frame_path))
            logger.info(f"[SECTIONS] Frame screenshot loaded: {frame_img.size}")
        except Exception as e:
            logger.warning(f"[SECTIONS] Could not load frame screenshot: {e}")

    scale_x = (frame_img.width / max(frame.width, 1)) if frame_img else 1.0
    scale_y = (frame_img.height / max(frame.height, 1)) if frame_img else 1.0

    sections = []
    for spec in specs:
        x, y, w, h = spec.crop_box
        # Scale crop_box to screenshot pixel space
        sx = int(x * scale_x); sy = int(y * scale_y)
        sw = max(1, int(w * scale_x)); sh = max(1, int(h * scale_y))
        if frame_img:
            sx = min(sx, frame_img.width - 1); sy = min(sy, frame_img.height - 1)
            sw = min(sw, frame_img.width - sx); sh = min(sh, frame_img.height - sy)
        thumb = _crop_to_b64(frame_img, (sx, sy, sw, sh)) if frame_img else None

        sections.append({
            "id": spec.node.id,
            "name": spec.name,
            "width": int(spec.node.width),
            "height": int(spec.node.height),
            "y_position": y,
            "is_template": spec.is_template,
            "instance_count": spec.instance_count,
            "thumbnail_b64": thumb,
        })

    return {"sections": sections, "frame_name": frame.name}


# ---------------------------------------------------------------------------
# POST /workflow/generate-section
# ---------------------------------------------------------------------------

class GenerateSectionRequest(BaseModel):
    figma_url: str
    frame_id: str
    section_id: str
    project_id: str


@app.post("/workflow/generate-section")
async def generate_section(request: GenerateSectionRequest):
    """Generate a single component from a Figma section and write it to an existing project."""
    file_id = _parse_file_id(request.figma_url)
    figma_token = os.getenv("FIGMA_TOKEN", "").strip()
    if not figma_token:
        raise HTTPException(status_code=500, detail="FIGMA_TOKEN not configured")

    figma_data = _load_figma_data(file_id, figma_token)

    try:
        from tools.production_figma_converter import FigmaNode, ProductionFigmaToCode
        from tools.component_decomposer import ComponentDecomposer
    except ImportError:
        from production_figma_converter import FigmaNode, ProductionFigmaToCode
        from component_decomposer import ComponentDecomposer

    root = FigmaNode(figma_data.get("document", {}))
    frame = _find_node_by_id(root, request.frame_id)
    if frame is None:
        raise HTTPException(status_code=404, detail=f"Frame {request.frame_id!r} not found")

    specs = ComponentDecomposer().decompose(frame)
    # Find the target spec by section_id (normalised)
    spec = next(
        (s for s in specs
         if _find_node_by_id(s.node, request.section_id) is not None
         or s.node.id.replace("-", ":") == request.section_id.replace("-", ":")),
        None,
    )
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Section {request.section_id!r} not found in decomposition")

    # Sanitize component name (same rule as _convert_decomposed)
    import re as _re
    spec.name = _re.sub(r'[^a-zA-Z0-9]', '', spec.name)
    if spec.name and not spec.name[0].isupper():
        spec.name = spec.name[0].upper() + spec.name[1:]
    if not spec.name:
        spec.name = "Component"

    # Locate project directory
    projects_root = Path(__file__).parent.parent.parent / "mcp-automation" / "projects"
    project_dir = projects_root / request.project_id
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail=f"Project {request.project_id!r} not found at {project_dir}")

    components_dir = project_dir / "src" / "components"
    components_dir.mkdir(parents=True, exist_ok=True)

    # Rebuild image_map from existing public/images/ files
    # Files are named {node_id_safe}.png — reverse-map to node.id (colon form)
    images_dir = project_dir / "public" / "images"
    image_map: dict = {}
    if images_dir.exists():
        for img_file in images_dir.glob("*.png"):
            stem = img_file.stem                           # e.g. "1_3951"
            node_id_colon = stem.replace("_", ":", 1)     # best-effort reverse
            image_map[node_id_colon] = f"/images/{img_file.name}"
            image_map[stem] = f"/images/{img_file.name}"  # also map safe key directly

    # Crop frame screenshot for this component
    crops_dir = project_dir / "_crops"
    crops_dir.mkdir(exist_ok=True)
    cropped_path: Optional[str] = None

    frame_path = _frame_screenshot_path(file_id, request.frame_id)
    frame_img = None
    if frame_path:
        try:
            from PIL import Image as _PILImage
            frame_img = _PILImage.open(str(frame_path))
        except Exception:
            pass

    if frame_img:
        scale_x = frame_img.width / max(frame.width, 1)
        scale_y = frame_img.height / max(frame.height, 1)
        try:
            x, y, w, h = spec.crop_box
            sx = int(x * scale_x); sy = int(y * scale_y)
            sw = max(1, int(w * scale_x)); sh = max(1, int(h * scale_y))
            sx = min(sx, frame_img.width - 1); sy = min(sy, frame_img.height - 1)
            sw = min(sw, frame_img.width - sx); sh = min(sh, frame_img.height - sy)
            if sw > 0 and sh > 0:
                region = frame_img.crop((sx, sy, sx + sw, sy + sh))
                # Upscale to ≥1024px wide for Claude's benefit
                if region.width < 1024:
                    scale = 1024 / region.width
                    region = region.resize(
                        (1024, max(1, int(region.height * scale))),
                        resample=1,  # LANCZOS
                    )
                crop_file = crops_dir / f"{spec.name}_crop.png"
                region.save(str(crop_file))
                cropped_path = str(crop_file)
        except Exception as _e:
            logger.warning(f"[GEN-SECTION] Crop failed: {_e}")

    # Generate the component via Claude
    converter = ProductionFigmaToCode(figma_token)
    loop = asyncio.get_event_loop()
    code = await loop.run_in_executor(
        None,
        lambda: converter._generate_decomposed_component(spec, cropped_path, image_map),
    )
    if not code:
        # Programmatic fallback
        code = converter.code_generator.generate_component(spec.node, spec.name, image_map)

    # Normalize whitespace and write
    code = _re.sub(r'(return\s*\()[ \t]+(<)', r'\1\n    \2', code)
    comp_file = components_dir / f"{spec.name}.tsx"
    comp_file.write_text(code, encoding="utf-8")
    logger.info(f"[GEN-SECTION] ✅ Wrote {comp_file.name} ({len(code)} chars)")

    # Return cropped design screenshot as preview
    preview_b64 = None
    if frame_img:
        x, y, w, h = spec.crop_box
        preview_b64 = _crop_to_b64(frame_img, (
            int(x * scale_x), int(y * scale_y),
            max(1, int(w * scale_x)), max(1, int(h * scale_y)),
        ))

    return {
        "component_name": spec.name,
        "file_path": str(comp_file.relative_to(project_dir)),
        "code_length": len(code),
        "preview_b64": preview_b64,
    }


# ---------------------------------------------------------------------------
# POST /workflow/rerender
# ---------------------------------------------------------------------------

class RerenderRequest(BaseModel):
    project_id: str
    viewport_width: int = 1280
    viewport_height: int = 800


@app.post("/workflow/rerender")
async def rerender_project(request: RerenderRequest):
    """Re-run the render step on an existing project and return a screenshot b64."""
    projects_root = Path(__file__).parent.parent.parent / "mcp-automation" / "projects"
    project_dir = projects_root / request.project_id
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail=f"Project {request.project_id!r} not found")

    try:
        from tools.render_engine import RenderEngine
    except ImportError:
        try:
            from render_engine import RenderEngine
        except ImportError:
            raise HTTPException(status_code=500, detail="RenderEngine not available")

    engine = RenderEngine()
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: engine.render_project(
                str(project_dir),
                viewport_width=request.viewport_width,
                viewport_height=request.viewport_height,
            ),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Render failed: {e}")

    screenshot_path = result.get("screenshot_path") if isinstance(result, dict) else None
    if not screenshot_path or not Path(screenshot_path).exists():
        raise HTTPException(status_code=500, detail="Render did not produce a screenshot")

    import base64 as _b64
    screenshot_b64 = _b64.b64encode(Path(screenshot_path).read_bytes()).decode()
    return {"screenshot_b64": screenshot_b64}


@app.post("/workflow/start")
async def start_workflow(request: WorkflowRequest):
    """Start a new Figma-to-production workflow and execute the full pipeline"""
    try:
        figma_url = request.figma_url
        # Append node-id so the converter targets a specific frame
        if request.frame_id:
            separator = "&" if "?" in figma_url else "?"
            figma_url = f"{figma_url}{separator}node-id={request.frame_id}"
            logger.info(f"🎯 Frame targeted: {request.frame_id}")
        logger.info(f"🚀 Starting workflow for: {figma_url}")

        # Start workflow execution (runs in background)
        workflow = await workflow_executor.start_workflow(
            figma_url=figma_url,
            project_name=request.project_name
        )

        # Return workflow ID for tracking
        return {
            "success": True,
            "workflow_id": workflow.id,
            "message": f"Workflow started: {workflow.id}",
            "websocket_url": "ws://localhost:8002",
            "project_name": workflow.project_name
        }

    except Exception as e:
        logger.error(f"Failed to start workflow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/workflow/{workflow_id}")
async def get_workflow_status(workflow_id: str):
    """Get current workflow status"""
    workflow = workflow_manager.get_workflow(workflow_id)

    if not workflow:
        raise HTTPException(status_code=404, detail=f"Workflow not found: {workflow_id}")

    return workflow.to_dict()


@app.post("/workflow/{workflow_id}/approve")
async def approve_workflow(workflow_id: str):
    """Approve workflow and continue to deployment"""
    workflow = workflow_manager.get_workflow(workflow_id)

    if not workflow:
        raise HTTPException(status_code=404, detail=f"Workflow not found: {workflow_id}")

    if workflow.state != WorkflowState.AWAITING_APPROVAL:
        raise HTTPException(
            status_code=400,
            detail=f"Workflow is not awaiting approval (current state: {workflow.state.value})"
        )

    # Transition to deploying
    await workflow_manager.transition(
        workflow,
        WorkflowState.DEPLOYING,
        step_name="Creating GitHub repo",
        progress=70,
        message="Deploying to production..."
    )

    workflow.approval_status = "approved"

    return {
        "success": True,
        "message": "Workflow approved, deploying...",
        "workflow_id": workflow_id
    }


@app.post("/workflow/{workflow_id}/reject")
async def reject_workflow(workflow_id: str, request: ApprovalRequest):
    """Reject workflow and request changes"""
    workflow = workflow_manager.get_workflow(workflow_id)

    if not workflow:
        raise HTTPException(status_code=404, detail=f"Workflow not found: {workflow_id}")

    if workflow.state != WorkflowState.AWAITING_APPROVAL:
        raise HTTPException(
            status_code=400,
            detail=f"Workflow is not awaiting approval (current state: {workflow.state.value})"
        )

    # Transition to regenerating
    await workflow_manager.transition(
        workflow,
        WorkflowState.REGENERATING,
        step_name="Applying changes",
        progress=40,
        message="Regenerating with requested changes..."
    )

    workflow.approval_status = "rejected"

    return {
        "success": True,
        "message": "Workflow rejected, regenerating...",
        "workflow_id": workflow_id,
        "requested_changes": request.requested_changes
    }


@app.delete("/workflow/{workflow_id}")
async def cancel_workflow(workflow_id: str):
    """Cancel a workflow"""
    workflow = workflow_manager.get_workflow(workflow_id)

    if not workflow:
        raise HTTPException(status_code=404, detail=f"Workflow not found: {workflow_id}")

    await workflow_manager.transition(
        workflow,
        WorkflowState.CANCELLED,
        message="Workflow cancelled by user"
    )

    return {
        "success": True,
        "message": "Workflow cancelled",
        "workflow_id": workflow_id
    }


@app.get("/workflows")
async def list_workflows():
    """List all workflows"""
    return {
        "workflows": workflow_manager.get_all_workflows(),
        "active_count": len(workflow_manager.get_active_workflows())
    }


@app.get("/workflows/active")
async def list_active_workflows():
    """List active (in-progress) workflows"""
    return {
        "workflows": workflow_manager.get_active_workflows()
    }


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import uvicorn

    logger.info("=" * 60)
    logger.info("🚀 GodComet Backend - Full-Featured AI Assistant")
    logger.info("=" * 60)
    logger.info("📡 REST API: http://localhost:8001")
    logger.info("🔌 WebSocket: ws://localhost:8002")
    logger.info("💡 Make sure your Electron app connects to these URLs")
    logger.info("=" * 60)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8001,
        log_level="info"
    )