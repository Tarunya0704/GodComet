"""
GodComet Backend - Connects to your MCP tools
"""
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import sys
from pathlib import Path

# Add MCP tools to path
mcp_tools_path = Path(__file__).parent / "mcp_tools"
sys.path.append(str(mcp_tools_path.parent.parent / "mcp-automation" / "src"))

# Import your existing MCP tools
try:
    from tools.figma_to_website_tool import FigmaToWebsiteTool
    from tools.document_generator_tool import DocumentGeneratorTool
    from tools.browser_tool import BrowserTool
    print("✅ MCP tools imported successfully!")
except ImportError as e:
    print(f"⚠️  Could not import MCP tools: {e}")
    print("Make sure to create symlink: ln -s ../../mcp-automation/src/tools mcp_tools")

app = FastAPI(title="GodComet Backend")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize tools
figma_tool = None
doc_tool = None
browser_tool = None

@app.on_event("startup")
async def startup():
    global figma_tool, doc_tool, browser_tool
    try:
        figma_tool = FigmaToWebsiteTool()
        doc_tool = DocumentGeneratorTool()
        browser_tool = BrowserTool()
        print("✅ All tools initialized!")
    except Exception as e:
        print(f"⚠️  Tool initialization error: {e}")

@app.get("/")
async def root():
    return {"status": "GodComet Backend Running", "version": "1.0.0"}

@app.post("/execute")
async def execute_command(request: dict):
    """Execute command using MCP tools"""
    command = request.get("command")
    context = request.get("context", {})
    
    print(f"🤖 Executing: {command}")
    print(f"📍 Context: {context}")
    
    # Simple command routing
    if "figma" in command.lower() or "website" in command.lower():
        # Use Figma tool
        return {"success": True, "message": "Figma tool would execute here"}
    
    elif "document" in command.lower() or "doc" in command.lower():
        # Use document tool
        return {"success": True, "message": "Document tool would execute here"}
    
    elif "browser" in command.lower() or "open" in command.lower():
        # Use browser tool
        return {"success": True, "message": "Browser tool would execute here"}
    
    else:
        return {
            "success": True,
            "message": f"Executed: {command}",
            "actions": [
                {"type": "analyzed", "description": "Command analyzed"},
                {"type": "executed", "description": "Action completed"}
            ]
        }

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for real-time updates"""
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"Echo: {data}")
    except:
        pass

if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting GodComet Backend...")
    print("📡 Connect your MCP tools by creating symlink:")
    print("   ln -s ../../mcp-automation/src/tools mcp_tools")
    uvicorn.run(app, host="0.0.0.0", port=8001)