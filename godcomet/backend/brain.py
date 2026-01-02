"""
GodComet Backend - Connects Electron to MCP Automation
WITH FULL CONTEXT AWARENESS + Code Analysis + Web Scraping
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sys
from pathlib import Path
import os
from dotenv import load_dotenv
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
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
        logger.info("=" * 60)
        
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

if __name__ == "__main__":
    import uvicorn
    
    logger.info("=" * 60)
    logger.info("🚀 GodComet Backend - Full-Featured AI Assistant")
    logger.info("=" * 60)
    logger.info("📡 Starting server on http://localhost:8001")
    logger.info("💡 Make sure your Electron app connects to this URL")
    logger.info("=" * 60)
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8001,
        log_level="info"
    )