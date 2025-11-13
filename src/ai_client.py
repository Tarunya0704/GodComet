# """AI Client with Groq - Ultra-fast AI inference"""
# from groq import Groq
# from .mcp_server import MCPServer
# from .database import DatabaseManager
# import time
# import json
# import logging

# logger = logging.getLogger(__name__)

# class AIClient:
#     """AI client using Groq with MCP"""
    
#     def __init__(self, api_key: str, mcp_server: MCPServer):
#         # Initialize Groq client
#         self.client = Groq(api_key=api_key)
#         self.mcp = mcp_server
#         self.db = DatabaseManager()
#         logger.info("Groq client initialized")
    
#     async def execute(self, command: str) -> dict:
#         """Execute command with AI"""
#         task_id = f"task_{int(time.time())}"
#         start_time = time.time()
        
#         logger.info(f"Executing: {command}")
        
#         try:
#             # Get tools from MCP
#             tools_list = await self.mcp.get_tools_list()
            
#             # Convert to Groq function format (same as OpenAI)
#             tools_for_groq = []
#             for t in tools_list:
#                 tools_for_groq.append({
#                     "type": "function",
#                     "function": {
#                         "name": t.name,
#                         "description": t.description,
#                         "parameters": t.inputSchema
#                     }
#                 })
            
#             logger.info(f"Available tools: {[t['function']['name'] for t in tools_for_groq]}")
            
#             # Create messages
#             messages = [
#                 {
#                     "role": "system",
#                     "content": "You are an AI automation assistant powered by Groq. Use the available tools to complete user tasks. Be thorough and provide clear feedback about what you're doing. Always use the tools provided rather than just explaining what to do."
#                 },
#                 {
#                     "role": "user",
#                     "content": f"Execute this task: {command}"
#                 }
#             ]
            
#             # AI loop with function calling
#             iteration = 0
#             max_iterations = 10
            
#             while iteration < max_iterations:
#                 iteration += 1
#                 logger.info(f"Groq iteration {iteration}/{max_iterations}")
                
#                 # Call Groq API (using llama model with function calling support)
#                 response = self.client.chat.completions.create(
#                     model="llama-3.3-70b-versatile",  # Best model for function calling
#                     messages=messages,
#                     tools=tools_for_groq,
#                     tool_choice="auto",
#                     temperature=0.1,
#                     max_tokens=4096
#                 )
                
#                 assistant_message = response.choices[0].message
#                 logger.info(f"Groq response - has tool calls: {bool(assistant_message.tool_calls)}")
                
#                 # Check if AI wants to call functions
#                 if assistant_message.tool_calls:
#                     # Add assistant message to conversation
#                     messages.append({
#                         "role": "assistant",
#                         "content": assistant_message.content,
#                         "tool_calls": [
#                             {
#                                 "id": tc.id,
#                                 "type": "function",
#                                 "function": {
#                                     "name": tc.function.name,
#                                     "arguments": tc.function.arguments
#                                 }
#                             }
#                             for tc in assistant_message.tool_calls
#                         ]
#                     })
                    
#                     # Execute each tool
#                     for tool_call in assistant_message.tool_calls:
#                         function_name = tool_call.function.name
#                         function_args = json.loads(tool_call.function.arguments)
                        
#                         logger.info(f"Executing tool: {function_name} with args: {function_args}")
                        
#                         try:
#                             # Call the tool through MCP
#                             result = await self.mcp.execute_tool(
#                                 function_name,
#                                 function_args
#                             )
                            
#                             # Format result text
#                             if result.get("success"):
#                                 result_text = f"✅ {result.get('message', 'Success')}"
#                                 if result.get('data'):
#                                     # Add important data
#                                     data = result['data']
#                                     if 'title' in data:
#                                         result_text += f"\nVideo Title: {data['title']}"
#                                     if 'url' in data:
#                                         result_text += f"\nURL: {data['url']}"
#                                     if 'buckets' in data:
#                                         result_text += f"\nBuckets: {', '.join(data['buckets'][:5])}"
#                                     if 'files' in data:
#                                         result_text += f"\nFiles found: {len(data['files'])}"
#                                     if 'content' in data:
#                                         content_preview = data['content'][:200]
#                                         result_text += f"\nContent preview: {content_preview}..."
#                             else:
#                                 result_text = f"❌ Error: {result.get('error', 'Unknown error')}"
                            
#                             logger.info(f"Tool result: {result_text[:100]}")
                            
#                             # Add tool result to messages
#                             messages.append({
#                                 "role": "tool",
#                                 "tool_call_id": tool_call.id,
#                                 "content": result_text
#                             })
                            
#                         except Exception as e:
#                             logger.error(f"Tool execution error: {e}", exc_info=True)
#                             messages.append({
#                                 "role": "tool",
#                                 "tool_call_id": tool_call.id,
#                                 "content": f"❌ Error: {str(e)}"
#                             })
                    
#                     # Continue loop to let AI process results
#                     continue
                
#                 else:
#                     # AI is done - no more function calls
#                     final_text = assistant_message.content or "Task completed successfully"
                    
#                     execution_time = time.time() - start_time
#                     result = {
#                         "message": final_text,
#                         "iterations": iteration
#                     }
                    
#                     logger.info(f"Task completed in {execution_time:.2f}s with {iteration} iterations")
#                     self.db.save_task(task_id, command, "completed", result, None, execution_time)
                    
#                     return {
#                         "success": True,
#                         "result": result,
#                         "execution_time": execution_time
#                     }
            
#             # Max iterations reached
#             execution_time = time.time() - start_time
#             error_msg = f"Max iterations ({max_iterations}) reached"
#             logger.warning(error_msg)
#             self.db.save_task(task_id, command, "failed", None, error_msg, execution_time)
#             return {"success": False, "error": error_msg}
            
#         except Exception as e:
#             logger.error(f"Execution failed: {e}", exc_info=True)
#             execution_time = time.time() - start_time
#             self.db.save_task(task_id, command, "failed", None, str(e), execution_time)
#             return {"success": False, "error": str(e)}

"""AI Client with Groq - IMPROVED for better natural language understanding"""
from groq import Groq
from .mcp_server import MCPServer
from .database import DatabaseManager
import time
import json
import logging

logger = logging.getLogger(__name__)

class AIClient:
    """AI client using Groq with MCP - Enhanced with better intent understanding"""
    
    def __init__(self, api_key: str, mcp_server: MCPServer):
        # Initialize Groq client
        self.client = Groq(api_key=api_key)
        self.mcp = mcp_server
        self.db = DatabaseManager()
        logger.info("Groq client initialized")
    
    async def execute(self, command: str) -> dict:
        """Execute command with AI"""
        task_id = f"task_{int(time.time())}"
        start_time = time.time()
        
        logger.info(f"Executing: {command}")
        
        try:
            # Get tools from MCP
            tools_list = await self.mcp.get_tools_list()
            
            # Convert to Groq function format (same as OpenAI)
            tools_for_groq = []
            for t in tools_list:
                tools_for_groq.append({
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.inputSchema
                    }
                })
            
            logger.info(f"Available tools: {[t['function']['name'] for t in tools_for_groq]}")
            
            # Create messages with ENHANCED system prompt
            messages = [
                {
                    "role": "system",
                    "content": """You are an AI automation assistant powered by Groq. Use the available tools to complete user tasks.

🎯 CRITICAL INSTRUCTIONS - Read Carefully:

1. **BE FLEXIBLE WITH LANGUAGE**: Users don't use exact tool names. Understand their INTENT.
2. **ALWAYS USE TOOLS**: Never refuse because of wording. Map user intent to closest tool.
3. **BE SMART**: Make reasonable assumptions about what the user wants.
4. **DON'T BE PEDANTIC**: If user says "projects" but tool says "deployments", use it anyway if it makes sense.

📋 COMMON INTENT MAPPINGS (Learn These):

**GitHub Requests:**
- "create repo/repository" → github_create_repo
- "push code/upload/send to github" → github_push_code
- "generate readme/make readme" → github_generate_readme
- "build project/setup github/push everything" → github_build_and_push

**Vercel Requests:**
- "list projects/deployments/apps/sites" → vercel_list_deployments (yes, it shows projects!)
- "deploy/publish/go live/launch" → vercel_deploy
- "show my apps/my sites/my deployments" → vercel_list_deployments

**Browser Requests:**
- "play/watch/open youtube" → youtube_play
- "go to/visit/open website" → browser_navigate
- "screenshot/capture/take picture" → browser_screenshot

**Jira Requests:**
- "complete assignment/do jira/create jira" → jira_create_assignment or jira_create_visual_with_screenshots

**File Requests:**
- "list files/show files/what files" → list_directory
- "read file/show file/open file" → file_read
- "write file/create file/save file" → file_write

🚨 IMPORTANT RULES:
- If user says "list my vercel projects" → USE vercel_list_deployments (it lists projects!)
- If user says "show my github repos" → USE github_list (if available) or explain they need to check github.com
- If user is close to any tool intent → USE THAT TOOL
- Don't say "function doesn't support that" → BE CREATIVE, use closest tool
- The tool name doesn't have to match user words exactly → understand MEANING

💡 EXAMPLES OF GOOD BEHAVIOR:
User: "list my vercel projects"
You: *calls vercel_list_deployments* ✅

User: "show me what's on vercel"
You: *calls vercel_list_deployments* ✅

User: "what apps do I have deployed"
You: *calls vercel_list_deployments* ✅

User: "create a new github thing"
You: *calls github_create_repo* ✅

Remember: Be helpful, flexible, and smart. Users don't know exact tool names!"""
                },
                {
                    "role": "user",
                    "content": f"Execute this task: {command}"
                }
            ]
            
            # AI loop with function calling
            iteration = 0
            max_iterations = 10
            
            while iteration < max_iterations:
                iteration += 1
                logger.info(f"Groq iteration {iteration}/{max_iterations}")
                
                # Call Groq API (using llama model with function calling support)
                response = self.client.chat.completions.create(
                    model="llama-3.3-70b-versatile",  # Best model for function calling
                    messages=messages,
                    tools=tools_for_groq,
                    tool_choice="auto",
                    temperature=0.1,
                    max_tokens=4096
                )
                
                assistant_message = response.choices[0].message
                logger.info(f"Groq response - has tool calls: {bool(assistant_message.tool_calls)}")
                
                # Check if AI wants to call functions
                if assistant_message.tool_calls:
                    # Add assistant message to conversation
                    messages.append({
                        "role": "assistant",
                        "content": assistant_message.content,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments
                                }
                            }
                            for tc in assistant_message.tool_calls
                        ]
                    })
                    
                    # Execute each tool
                    for tool_call in assistant_message.tool_calls:
                        function_name = tool_call.function.name
                        function_args = json.loads(tool_call.function.arguments)
                        
                        logger.info(f"Executing tool: {function_name} with args: {function_args}")
                        
                        try:
                            # Call the tool through MCP
                            result = await self.mcp.execute_tool(
                                function_name,
                                function_args
                            )
                            
                            # Format result text
                            if result.get("success"):
                                result_text = f"✅ {result.get('message', 'Success')}"
                                if result.get('data'):
                                    # Add important data
                                    data = result['data']
                                    
                                    # Video/YouTube data
                                    if 'title' in data:
                                        result_text += f"\nVideo Title: {data['title']}"
                                    
                                    # Website/Deployment URLs (PROMINENT DISPLAY)
                                    if 'vercel_url' in data and data['vercel_url']:
                                        result_text += f"\n\n{'='*60}"
                                        result_text += f"\n🌐 LIVE WEBSITE: {data['vercel_url']}"
                                        result_text += f"\n{'='*60}"
                                        result_text += f"\n✨ Your website is now live! Click the link above to visit."
                                    
                                    # GitHub URLs
                                    if 'github_url' in data and data['github_url']:
                                        result_text += f"\n\n📦 GitHub Repository: {data['github_url']}"
                                    if 'repo_url' in data and data['repo_url']:
                                        result_text += f"\n📦 Repository: {data['repo_url']}"
                                    
                                    # Local paths
                                    if 'local_path' in data:
                                        result_text += f"\n📁 Local Files: {data['local_path']}"
                                    
                                    # Document files
                                    if 'word_document' in data:
                                        result_text += f"\n📄 Word Document: {data['word_document']}"
                                    if 'powerpoint' in data:
                                        result_text += f"\n📊 PowerPoint: {data['powerpoint']}"
                                    
                                    # Project info
                                    if 'project_name' in data:
                                        result_text += f"\n🏷️  Project: {data['project_name']}"
                                    
                                    # Other URLs
                                    if 'url' in data and 'vercel_url' not in data:
                                        result_text += f"\n🔗 URL: {data['url']}"
                                    
                                    # Deployments list
                                    if 'deployments' in data:
                                        result_text += f"\n\n📋 Deployments: {len(data['deployments'])}"
                                        for dep in data['deployments'][:3]:  # Show first 3
                                            result_text += f"\n  • {dep.get('name', 'Unknown')}: {dep.get('url', 'N/A')}"
                                    
                                    # AWS buckets
                                    if 'buckets' in data:
                                        result_text += f"\nBuckets: {', '.join(data['buckets'][:5])}"
                                    
                                    # Files
                                    if 'files' in data and isinstance(data['files'], list):
                                        result_text += f"\n📂 Files Created: {len(data['files'])} files"
                                    
                                    # Content preview
                                    if 'content' in data:
                                        content_preview = data['content'][:200]
                                        result_text += f"\nContent preview: {content_preview}..."
                            else:
                                result_text = f"❌ Error: {result.get('error', 'Unknown error')}"
                            
                            logger.info(f"Tool result: {result_text[:100]}")
                            
                            # Add tool result to messages
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": result_text
                            })
                            
                        except Exception as e:
                            logger.error(f"Tool execution error: {e}", exc_info=True)
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": f"❌ Error: {str(e)}"
                            })
                    
                    # Continue loop to let AI process results
                    continue
                
                else:
                    # AI is done - no more function calls
                    final_text = assistant_message.content or "Task completed successfully"
                    
                    execution_time = time.time() - start_time
                    result = {
                        "message": final_text,
                        "iterations": iteration
                    }
                    
                    logger.info(f"Task completed in {execution_time:.2f}s with {iteration} iterations")
                    self.db.save_task(task_id, command, "completed", result, None, execution_time)
                    
                    return {
                        "success": True,
                        "result": result,
                        "execution_time": execution_time
                    }
            
            # Max iterations reached
            execution_time = time.time() - start_time
            error_msg = f"Max iterations ({max_iterations}) reached"
            logger.warning(error_msg)
            self.db.save_task(task_id, command, "failed", None, error_msg, execution_time)
            return {"success": False, "error": error_msg}
            
        except Exception as e:
            logger.error(f"Execution failed: {e}", exc_info=True)
            execution_time = time.time() - start_time
            self.db.save_task(task_id, command, "failed", None, str(e), execution_time)
            return {"success": False, "error": str(e)}