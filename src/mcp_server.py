"""MCP Server implementation - Fixed for MCP 1.19.0+"""
from mcp.server import Server
from mcp.types import Tool, TextContent
from .tools import BrowserTool, AWSTool, SystemTool
from .database import DatabaseManager
import logging

logger = logging.getLogger(__name__)

class MCPServer:
    """MCP Server managing automation tools"""
    
    def __init__(self):
        self.server = Server("automation-server")
        self.browser = BrowserTool()
        self.aws = None
        self.system = SystemTool()
        self.db = DatabaseManager()
        
        # Store tools list manually
        self.tools_list = []
        
        self._register_tools()
    
    def configure_aws(self, access_key: str, secret_key: str, region: str):
        """Configure AWS"""
        self.aws = AWSTool(access_key, secret_key, region)
        logger.info(f"AWS configured: {region}")
    
    def _register_tools(self):
        """Register MCP tools"""
        
        # Define all tools
        self.tools_list = [
            Tool(
                name="browser_navigate",
                description="Navigate to a URL in the browser",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to navigate to"}
                    },
                    "required": ["url"]
                }
            ),
            Tool(
                name="youtube_play",
                description="Search and play a video on YouTube",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Video search query"}
                    },
                    "required": ["query"]
                }
            ),
            Tool(
                name="browser_screenshot",
                description="Take a screenshot of the current page",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string", 
                            "description": "Optional filename for screenshot"
                        }
                    }
                }
            ),
            Tool(
                name="aws_create_bucket",
                description="Create an AWS S3 bucket",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "bucket_name": {
                            "type": "string",
                            "description": "Name of the bucket to create"
                        }
                    },
                    "required": ["bucket_name"]
                }
            ),
            Tool(
                name="aws_list_buckets",
                description="List all AWS S3 buckets",
                inputSchema={
                    "type": "object",
                    "properties": {}
                }
            ),
            Tool(
                name="file_read",
                description="Read contents of a file",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the file"}
                    },
                    "required": ["path"]
                }
            ),
            Tool(
                name="file_write",
                description="Write content to a file",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the file"},
                        "content": {"type": "string", "description": "Content to write"}
                    },
                    "required": ["path", "content"]
                }
            ),
            Tool(
                name="list_directory",
                description="List contents of a directory",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Directory path (default: current directory)"
                        }
                    }
                }
            ),
        ]
        
        logger.info(f"Registered {len(self.tools_list)} MCP tools")
        
        # Register handlers with MCP server
        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            """Return list of available tools"""
            return self.tools_list
        
        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[TextContent]:
            """Execute a tool"""
            logger.info(f"Tool called: {name} with args: {arguments}")
            
            try:
                result = None
                
                # Browser tools
                if name == "browser_navigate":
                    result = await self.browser.navigate(arguments["url"])
                    
                elif name == "youtube_play":
                    result = await self.browser.play_youtube(arguments["query"])
                    
                elif name == "browser_screenshot":
                    filename = arguments.get("filename", "screenshot.png")
                    result = await self.browser.screenshot(filename)
                
                # AWS tools
                elif name == "aws_create_bucket":
                    if not self.aws:
                        result = {"success": False, "error": "AWS not configured"}
                    else:
                        result = await self.aws.create_bucket(arguments["bucket_name"])
                        
                elif name == "aws_list_buckets":
                    if not self.aws:
                        result = {"success": False, "error": "AWS not configured"}
                    else:
                        result = await self.aws.list_buckets()
                
                # System tools
                elif name == "file_read":
                    result = await self.system.read_file(arguments["path"])
                    
                elif name == "file_write":
                    result = await self.system.write_file(
                        arguments["path"],
                        arguments["content"]
                    )
                    
                elif name == "list_directory":
                    path = arguments.get("path", ".")
                    result = await self.system.list_directory(path)
                
                else:
                    result = {"success": False, "error": f"Unknown tool: {name}"}
                
                # Log tool usage
                self.db.log_tool_usage(name, result.get("success", False), 0)
                
                # Format response
                if result.get("success"):
                    message = f"✅ {result.get('message', 'Success')}"
                    if result.get('data'):
                        # Add relevant data to message
                        if 'title' in result['data']:
                            message += f"\nTitle: {result['data']['title']}"
                        if 'buckets' in result['data']:
                            message += f"\nBuckets: {', '.join(result['data']['buckets'][:5])}"
                        if 'files' in result['data']:
                            message += f"\nFiles: {len(result['data']['files'])}"
                        if 'content' in result['data']:
                            content = result['data']['content'][:200]
                            message += f"\nContent: {content}..."
                else:
                    message = f"❌ Error: {result.get('error', 'Unknown error')}"
                
                return [TextContent(type="text", text=message)]
                
            except Exception as e:
                logger.error(f"Tool execution error: {e}", exc_info=True)
                return [TextContent(
                    type="text",
                    text=f"❌ Tool execution failed: {str(e)}"
                )]
    
    async def get_tools_list(self):
        """Get list of available tools"""
        return self.tools_list
    
    async def execute_tool(self, name: str, arguments: dict):
        """Execute a tool directly"""
        logger.info(f"Executing tool: {name} with args: {arguments}")
        
        try:
            result = None
            
            # Browser tools
            if name == "browser_navigate":
                result = await self.browser.navigate(arguments["url"])
                
            elif name == "youtube_play":
                result = await self.browser.play_youtube(arguments["query"])
                
            elif name == "browser_screenshot":
                filename = arguments.get("filename", "screenshot.png")
                result = await self.browser.screenshot(filename)
            
            # AWS tools
            elif name == "aws_create_bucket":
                if not self.aws:
                    result = {"success": False, "error": "AWS not configured"}
                else:
                    result = await self.aws.create_bucket(arguments["bucket_name"])
                    
            elif name == "aws_list_buckets":
                if not self.aws:
                    result = {"success": False, "error": "AWS not configured"}
                else:
                    result = await self.aws.list_buckets()
            
            # System tools
            elif name == "file_read":
                result = await self.system.read_file(arguments["path"])
                
            elif name == "file_write":
                result = await self.system.write_file(
                    arguments["path"],
                    arguments["content"]
                )
                
            elif name == "list_directory":
                path = arguments.get("path", ".")
                result = await self.system.list_directory(path)
            
            else:
                result = {"success": False, "error": f"Unknown tool: {name}"}
            
            # Log usage
            self.db.log_tool_usage(name, result.get("success", False), 0)
            
            return result
            
        except Exception as e:
            logger.error(f"Tool execution error: {e}", exc_info=True)
            return {"success": False, "error": str(e)}