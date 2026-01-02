# # """AI Client with Groq - Ultra-fast AI inference"""
# # from groq import Groq
# # from .mcp_server import MCPServer
# # from .database import DatabaseManager
# # import time
# # import json
# # import logging

# # logger = logging.getLogger(__name__)

# # class AIClient:
# #     """AI client using Groq with MCP"""
    
# #     def __init__(self, api_key: str, mcp_server: MCPServer):
# #         # Initialize Groq client
# #         self.client = Groq(api_key=api_key)
# #         self.mcp = mcp_server
# #         self.db = DatabaseManager()
# #         logger.info("Groq client initialized")
    
# #     async def execute(self, command: str) -> dict:
# #         """Execute command with AI"""
# #         task_id = f"task_{int(time.time())}"
# #         start_time = time.time()
        
# #         logger.info(f"Executing: {command}")
        
# #         try:
# #             # Get tools from MCP
# #             tools_list = await self.mcp.get_tools_list()
            
# #             # Convert to Groq function format (same as OpenAI)
# #             tools_for_groq = []
# #             for t in tools_list:
# #                 tools_for_groq.append({
# #                     "type": "function",
# #                     "function": {
# #                         "name": t.name,
# #                         "description": t.description,
# #                         "parameters": t.inputSchema
# #                     }
# #                 })
            
# #             logger.info(f"Available tools: {[t['function']['name'] for t in tools_for_groq]}")
            
# #             # Create messages
# #             messages = [
# #                 {
# #                     "role": "system",
# #                     "content": "You are an AI automation assistant powered by Groq. Use the available tools to complete user tasks. Be thorough and provide clear feedback about what you're doing. Always use the tools provided rather than just explaining what to do."
# #                 },
# #                 {
# #                     "role": "user",
# #                     "content": f"Execute this task: {command}"
# #                 }
# #             ]
            
# #             # AI loop with function calling
# #             iteration = 0
# #             max_iterations = 10
            
# #             while iteration < max_iterations:
# #                 iteration += 1
# #                 logger.info(f"Groq iteration {iteration}/{max_iterations}")
                
# #                 # Call Groq API (using llama model with function calling support)
# #                 response = self.client.chat.completions.create(
# #                     model="llama-3.3-70b-versatile",  # Best model for function calling
# #                     messages=messages,
# #                     tools=tools_for_groq,
# #                     tool_choice="auto",
# #                     temperature=0.1,
# #                     max_tokens=4096
# #                 )
                
# #                 assistant_message = response.choices[0].message
# #                 logger.info(f"Groq response - has tool calls: {bool(assistant_message.tool_calls)}")
                
# #                 # Check if AI wants to call functions
# #                 if assistant_message.tool_calls:
# #                     # Add assistant message to conversation
# #                     messages.append({
# #                         "role": "assistant",
# #                         "content": assistant_message.content,
# #                         "tool_calls": [
# #                             {
# #                                 "id": tc.id,
# #                                 "type": "function",
# #                                 "function": {
# #                                     "name": tc.function.name,
# #                                     "arguments": tc.function.arguments
# #                                 }
# #                             }
# #                             for tc in assistant_message.tool_calls
# #                         ]
# #                     })
                    
# #                     # Execute each tool
# #                     for tool_call in assistant_message.tool_calls:
# #                         function_name = tool_call.function.name
# #                         function_args = json.loads(tool_call.function.arguments)
                        
# #                         logger.info(f"Executing tool: {function_name} with args: {function_args}")
                        
# #                         try:
# #                             # Call the tool through MCP
# #                             result = await self.mcp.execute_tool(
# #                                 function_name,
# #                                 function_args
# #                             )
                            
# #                             # Format result text
# #                             if result.get("success"):
# #                                 result_text = f"✅ {result.get('message', 'Success')}"
# #                                 if result.get('data'):
# #                                     # Add important data
# #                                     data = result['data']
# #                                     if 'title' in data:
# #                                         result_text += f"\nVideo Title: {data['title']}"
# #                                     if 'url' in data:
# #                                         result_text += f"\nURL: {data['url']}"
# #                                     if 'buckets' in data:
# #                                         result_text += f"\nBuckets: {', '.join(data['buckets'][:5])}"
# #                                     if 'files' in data:
# #                                         result_text += f"\nFiles found: {len(data['files'])}"
# #                                     if 'content' in data:
# #                                         content_preview = data['content'][:200]
# #                                         result_text += f"\nContent preview: {content_preview}..."
# #                             else:
# #                                 result_text = f"❌ Error: {result.get('error', 'Unknown error')}"
                            
# #                             logger.info(f"Tool result: {result_text[:100]}")
                            
# #                             # Add tool result to messages
# #                             messages.append({
# #                                 "role": "tool",
# #                                 "tool_call_id": tool_call.id,
# #                                 "content": result_text
# #                             })
                            
# #                         except Exception as e:
# #                             logger.error(f"Tool execution error: {e}", exc_info=True)
# #                             messages.append({
# #                                 "role": "tool",
# #                                 "tool_call_id": tool_call.id,
# #                                 "content": f"❌ Error: {str(e)}"
# #                             })
                    
# #                     # Continue loop to let AI process results
# #                     continue
                
# #                 else:
# #                     # AI is done - no more function calls
# #                     final_text = assistant_message.content or "Task completed successfully"
                    
# #                     execution_time = time.time() - start_time
# #                     result = {
# #                         "message": final_text,
# #                         "iterations": iteration
# #                     }
                    
# #                     logger.info(f"Task completed in {execution_time:.2f}s with {iteration} iterations")
# #                     self.db.save_task(task_id, command, "completed", result, None, execution_time)
                    
# #                     return {
# #                         "success": True,
# #                         "result": result,
# #                         "execution_time": execution_time
# #                     }
            
# #             # Max iterations reached
# #             execution_time = time.time() - start_time
# #             error_msg = f"Max iterations ({max_iterations}) reached"
# #             logger.warning(error_msg)
# #             self.db.save_task(task_id, command, "failed", None, error_msg, execution_time)
# #             return {"success": False, "error": error_msg}
            
# #         except Exception as e:
# #             logger.error(f"Execution failed: {e}", exc_info=True)
# #             execution_time = time.time() - start_time
# #             self.db.save_task(task_id, command, "failed", None, str(e), execution_time)
# #             return {"success": False, "error": str(e)}

# """AI Client with Groq - CONTEXT-AWARE with direct answers and enhanced tool support"""
# from groq import Groq

# # Support both relative and absolute imports
# try:
#     from .mcp_server import MCPServer
# except ImportError:
#     from mcp_server import MCPServer

# try:
#     from .database import DatabaseManager
# except ImportError:
#     from database import DatabaseManager

# import time
# import json
# import logging

# logger = logging.getLogger(__name__)

# class AIClient:
#     """AI client using Groq with MCP - Enhanced with FULL context awareness"""
    
#     def __init__(self, api_key: str, mcp_server: MCPServer):
#         # Initialize Groq client
#         self.client = Groq(api_key=api_key)
#         self.mcp = mcp_server
#         self.db = DatabaseManager()
#         logger.info("Groq client initialized")
    
#     def _should_answer_from_context(self, command: str, context: dict) -> tuple:
#         """Check if we can answer directly from context without tools"""
#         if not context:
#             return False, None
        
#         command_lower = command.lower()
        
#         # Questions about current file
#         if any(x in command_lower for x in ['what file', 'which file', 'current file', 'file am i', 'file i am', 'working on']):
#             if context.get('file'):
#                 file_path = context['file']
#                 file_name = file_path.split('\\')[-1] if '\\' in file_path else file_path.split('/')[-1]
#                 language = context.get('language', 'unknown')
#                 return True, f"You're currently editing **{file_name}** ({language} file)\n\n📄 Full path: `{file_path}`"
#             else:
#                 return True, "No file is currently open in your editor."
        
#         # Questions about current app
#         if any(x in command_lower for x in ['what app', 'which app', 'what am i using', 'current app']):
#             if context.get('app'):
#                 return True, f"You're currently using: **{context['app']}**"
#             else:
#                 return True, "Unable to detect the current application."
        
#         # Questions about current website
#         if any(x in command_lower for x in ['what website', 'which site', 'what page', 'where am i', 'current url']):
#             if context.get('url'):
#                 return True, f"You're currently on: **{context['url']}**"
#             else:
#                 return True, "No website is currently open, or you're not in a browser."
        
#         return False, None
    
#     async def execute(self, command: str, context: dict = None) -> dict:
#         """Execute command with AI - NOW WITH DIRECT CONTEXT ANSWERS!"""
#         task_id = f"task_{int(time.time())}"
#         start_time = time.time()
        
#         logger.info(f"Executing: {command}")
#         logger.info(f"Context received: {context}")
        
#         try:
#             # ⭐ CHECK IF WE CAN ANSWER DIRECTLY FROM CONTEXT (NO TOOLS!)
#             should_answer, direct_answer = self._should_answer_from_context(command, context)
#             if should_answer:
#                 logger.info("✅ Answering directly from context (no tools needed)")
#                 execution_time = time.time() - start_time
#                 result = {
#                     "message": direct_answer,
#                     "iterations": 0
#                 }
#                 self.db.save_task(task_id, command, "completed", result, None, execution_time)
#                 return {
#                     "success": True,
#                     "result": result,
#                     "execution_time": execution_time
#                 }
            
#             # Get tools from MCP
#             tools_list = await self.mcp.get_tools_list()
            
#             # Convert to Groq function format
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
            
#             # ⭐ BUILD CONTEXT-AWARE PROMPT (NO CLIPBOARD!)
#             context_info = ""
#             if context:
#                 # Exclude clipboard to avoid token bloat
#                 context_summary = {
#                     'app': context.get('app', 'Unknown'),
#                     'file': context.get('file', 'None'),
#                     'window': context.get('window', 'None'),
#                     'url': context.get('url', 'None'),
#                     'selectedText': context.get('selectedText', 'None')[:200] if context.get('selectedText') else 'None',
#                 }
                
#                 context_info = f"""
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 🎯 CURRENT USER CONTEXT (USE THIS INFORMATION!):
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📱 Application: {context_summary['app']}
# 📄 Current File: {context_summary['file']}
# 🪟 Window Title: {context_summary['window']}
# 🌐 URL: {context_summary['url']}
# ✂️  Selected Text: {context_summary['selectedText']}
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ⚡ CRITICAL: Use this REAL context in your response!
# """
#             else:
#                 context_info = """
# ⚠️  NO CONTEXT AVAILABLE
# Tell user to open a file or application first.
# """
            
#             # Create messages with ENHANCED context-aware system prompt
#             messages = [
#                 {
#                     "role": "system",
#                     "content": f"""You are GodComet OS - an intelligent AI assistant with FULL context awareness.

# {context_info}

# 🎯 CRITICAL INSTRUCTIONS:

# 1. **WHEN TO USE TOOLS vs ANSWER DIRECTLY:**
#    ✅ ANSWER DIRECTLY (no tools) for:
#    - "what file am I editing" → Already answered before this point
#    - "what app am I using" → Already answered before this point
#    - Simple context questions → You have the answer above!
   
#    ✅ USE TOOLS for:
#    - "list workflows" → use list_workflows tool
#    - "play music" → use youtube_play tool
#    - "create repo" → use github_create_repo tool
#    - "list files" → use list_directory tool
#    - "read file X" → ONLY if asking about a DIFFERENT file than current

# 2. **TOOL SELECTION (COMPLETE LIST):**
   
#    📝 CODE ANALYSIS (use current file path from context):
#    - "analyze this code" / "check this code" → use analyze_code with current file path
#    - "fix this bug" / "fix bugs" → use fix_bugs with current file path
#    - "add tests" / "generate tests" / "create tests" → use generate_tests with current file path
#    - "refactor this" / "refactor this code" / "improve this code" → use refactor_code with current file path
#    - "document this code" / "add documentation" / "add docstrings" → use document_code with current file path
   
#    🌐 WEB SCRAPING & RESEARCH:
#    - "summarize this article" / "what is this article about" → use summarize_article (no URL needed if on page)
#    - "scrape this table" / "export table to csv" / "save table" → use scrape_table_to_csv
#    - "research competitors for X" / "find competitors" → use research_competitors with topic
   
#    🚀 DEPLOYMENT & GITHUB:
#    - "list vercel projects/deployments" → use vercel_list_deployments
#    - "create github repo" / "make a repo" → use github_create_repo
#    - "deploy to vercel" → use vercel_deploy
   
#    🎵 BROWSER & MEDIA:
#    - "play youtube/music" / "play X on youtube" → use youtube_play
#    - "navigate to X" / "go to X" → use browser_navigate
#    - "take screenshot" → use browser_screenshot
   
#    📂 FILE OPERATIONS:
#    - "list files" / "show files" → use list_directory
#    - "read file X" → use file_read (only for different file)
#    - "write to file" → use file_write
   
#    🔄 WORKFLOWS:
#    - "list workflows" → use list_workflows
#    - "execute workflow X" → use execute_workflow
   
#    📄 DOCUMENT GENERATION:
#    - "create document about X" / "make presentation" → use create_document_and_presentation
#    - "figma to website" → use figma_to_website

# 3. **ERROR HANDLING:**
#    - Don't repeat failed tools more than 2 times
#    - If tool fails with same error 2x, STOP and report
#    - If file read fails with encoding error, stop trying different encodings
#    - If browser closes, stop using browser tools
#    - Report errors clearly to user

# 4. **CONTEXT-AWARE BEHAVIOR:**
#    - When user says "this code" or "this file" → use the current file path from context
#    - When user says "this article" or "this page" → use current URL from context
#    - Always use context information to understand what the user is referring to

# Available tools: {[t['function']['name'] for t in tools_for_groq]}

# Remember: Answer simple context questions directly, use tools for actions!"""
#                 },
#                 {
#                     "role": "user",
#                     "content": f"Execute this task: {command}"
#                 }
#             ]
            
#             # AI loop with function calling and error detection
#             iteration = 0
#             max_iterations = 10
#             consecutive_failures = 0
#             last_error = None
            
#             while iteration < max_iterations:
#                 iteration += 1
#                 logger.info(f"Groq iteration {iteration}/{max_iterations}")
                
#                 try:
#                     # Call Groq API
#                     response = self.client.chat.completions.create(
#                         model="llama-3.1-8b-instant",
#                         messages=messages,
#                         tools=tools_for_groq,
#                         tool_choice="auto",
#                         temperature=0.1,
#                         max_tokens=2048
#                     )
#                 except Exception as api_error:
#                     logger.error(f"Groq API error: {api_error}")
#                     execution_time = time.time() - start_time
                    
#                     if "413" in str(api_error) or "too large" in str(api_error).lower():
#                         error_msg = "Request too large. Try a simpler command."
#                     elif "429" in str(api_error) or "rate_limit" in str(api_error).lower():
#                         error_msg = "Rate limit exceeded. Please wait a moment and try again."
#                     else:
#                         error_msg = f"API error: {str(api_error)}"
                    
#                     self.db.save_task(task_id, command, "failed", None, error_msg, execution_time)
#                     return {"success": False, "error": error_msg}
                
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
                            
#                             # ⭐ CHECK FOR COMPLETION FLAG
#                             if result.get("completed") is True:
#                                 logger.info("✅ Tool marked task as COMPLETED")
#                                 execution_time = time.time() - start_time
#                                 final_result = {
#                                     "message": result.get("message", "Task completed"),
#                                     "data": result.get("data", {}),
#                                     "iterations": iteration
#                                 }
#                                 self.db.save_task(task_id, command, "completed", final_result, None, execution_time)
#                                 return {
#                                     "success": True,
#                                     "result": final_result,
#                                     "execution_time": execution_time
#                                 }
                            
#                             # ⭐ CHECK FOR FATAL ERROR
#                             if result.get("fatal") is True:
#                                 logger.error("❌ Tool returned FATAL error")
#                                 execution_time = time.time() - start_time
#                                 error_msg = result.get("error", "Fatal error occurred")
#                                 self.db.save_task(task_id, command, "failed", None, error_msg, execution_time)
#                                 return {
#                                     "success": False,
#                                     "error": error_msg,
#                                     "execution_time": execution_time
#                                 }
                            
#                             # ⭐ DETECT REPEATED FAILURES
#                             if not result.get("success"):
#                                 error_text = result.get('error', '').lower()
                                
#                                 # Check for encoding errors (file_read issue)
#                                 if 'codec' in error_text or 'decode' in error_text or 'encoding' in error_text:
#                                     consecutive_failures += 1
#                                     last_error = "File encoding error"
                                    
#                                     if consecutive_failures >= 2:
#                                         logger.error(f"❌ Encoding error {consecutive_failures} times - STOPPING")
#                                         execution_time = time.time() - start_time
#                                         error_msg = "Unable to read file due to encoding issues. The file may contain special characters."
#                                         self.db.save_task(task_id, command, "failed", None, error_msg, execution_time)
#                                         return {
#                                             "success": False,
#                                             "error": error_msg,
#                                             "execution_time": execution_time
#                                         }
                                
#                                 # Check for browser errors
#                                 elif any(x in error_text for x in ['target page', 'browser has been closed', 'connection closed']):
#                                     consecutive_failures += 1
#                                     last_error = "Browser closed"
                                    
#                                     if consecutive_failures >= 3:
#                                         logger.error("❌ Browser error 3 times - STOPPING")
#                                         execution_time = time.time() - start_time
#                                         error_msg = "Browser tool failed. Please try a different command."
#                                         self.db.save_task(task_id, command, "failed", None, error_msg, execution_time)
#                                         return {
#                                             "success": False,
#                                             "error": error_msg,
#                                             "execution_time": execution_time
#                                         }
#                                 else:
#                                     consecutive_failures = 0
#                             else:
#                                 consecutive_failures = 0
                            
#                             # Format result text (TRUNCATED to avoid token bloat)
#                             if result.get("success"):
#                                 result_text = f"✅ {result.get('message', 'Success')}"
#                                 if result.get('data'):
#                                     data = result['data']
#                                     if 'vercel_url' in data and data['vercel_url']:
#                                         result_text += f"\n🌐 LIVE: {data['vercel_url']}"
#                                     if 'github_url' in data and data['github_url']:
#                                         result_text += f"\n📦 GitHub: {data['github_url']}"
#                                     if 'title' in data:
#                                         result_text += f"\n▶️  {data['title']}"
#                                     if 'url' in data and 'vercel_url' not in data:
#                                         result_text += f"\n🔗 {data['url']}"
#                                     # Code analysis results
#                                     if 'analysis' in data:
#                                         result_text += f"\n📊 Analysis complete"
#                                     if 'suggestions' in data:
#                                         result_text += f"\n💡 Suggestions provided"
#                                     if 'tests' in data:
#                                         result_text += f"\n🧪 Tests generated"
#                                     if 'refactored' in data:
#                                         result_text += f"\n♻️  Refactoring complete"
#                                     if 'documentation' in data:
#                                         result_text += f"\n📝 Documentation generated"
#                                     # Web scraping results
#                                     if 'summary' in data:
#                                         result_text += f"\n📰 Article summarized"
#                                     if 'results' in data:
#                                         result_text += f"\n🔍 Found {len(data.get('results', []))} results"
#                                 # Limit to 500 chars
#                                 result_text = result_text[:500]
#                             else:
#                                 result_text = f"❌ Error: {result.get('error', 'Unknown')}"
                            
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
                    
#                     # Continue loop
#                     continue
                
#                 else:
#                     # AI is done
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
            
#             # Max iterations
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
    
#     async def chat(self, message: str, conversation_history: list = None) -> dict:
#         """Simple chat without tools - used by code analysis and web scraping"""
#         try:
#             messages = conversation_history or []
#             messages.append({"role": "user", "content": message})
            
#             response = self.client.chat.completions.create(
#                 model="llama-3.1-8b-instant",
#                 messages=messages,
#                 temperature=0.7,
#                 max_tokens=2048
#             )
            
#             reply = response.choices[0].message.content
            
#             return {
#                 "success": True,
#                 "reply": reply,
#                 "usage": {
#                     "prompt_tokens": response.usage.prompt_tokens,
#                     "completion_tokens": response.usage.completion_tokens,
#                     "total_tokens": response.usage.total_tokens
#                 }
#             }
            
#         except Exception as e:
#             logger.error(f"Chat failed: {e}")
#             return {"success": False, "error": str(e)}

"""AI Client with Groq - CONTEXT-AWARE with FORCED tool usage for Windows automation"""
from groq import Groq

# Support both relative and absolute imports
try:
    from .mcp_server import MCPServer
except ImportError:
    from mcp_server import MCPServer

try:
    from .database import DatabaseManager
except ImportError:
    from database import DatabaseManager

import time
import json
import logging

logger = logging.getLogger(__name__)

class AIClient:
    """AI client using Groq with MCP - Enhanced with FORCED tool usage"""
    
    def __init__(self, api_key: str, mcp_server: MCPServer):
        # Initialize Groq client
        self.client = Groq(api_key=api_key)
        self.mcp = mcp_server
        self.db = DatabaseManager()
        logger.info("Groq client initialized")
    
    def _should_answer_from_context(self, command: str, context: dict) -> tuple:
        """Check if we can answer directly from context without tools"""
        if not context:
            return False, None
        
        command_lower = command.lower()
        
        # Questions about current file
        if any(x in command_lower for x in ['what file', 'which file', 'current file', 'file am i', 'file i am', 'working on']):
            if context.get('file'):
                file_path = context['file']
                file_name = file_path.split('\\')[-1] if '\\' in file_path else file_path.split('/')[-1]
                language = context.get('language', 'unknown')
                return True, f"You're currently editing **{file_name}** ({language} file)\n\n📄 Full path: `{file_path}`"
            else:
                return True, "No file is currently open in your editor."
        
        # Questions about current app
        if any(x in command_lower for x in ['what app', 'which app', 'what am i using', 'current app']):
            if context.get('app'):
                return True, f"You're currently using: **{context['app']}**"
            else:
                return True, "Unable to detect the current application."
        
        # Questions about current website
        if any(x in command_lower for x in ['what website', 'which site', 'what page', 'where am i', 'current url']):
            if context.get('url'):
                return True, f"You're currently on: **{context['url']}**"
            else:
                return True, "No website is currently open, or you're not in a browser."
        
        # Questions about current folder
        if any(x in command_lower for x in ['what folder', 'which folder', 'current folder']):
            if context.get('currentFolder'):
                return True, f"You're currently in folder: **{context['currentFolder']}**"
            else:
                return True, "No folder detected or File Explorer not open."
        
        return False, None
    
    async def execute(self, command: str, context: dict = None) -> dict:
        """Execute command with AI - FORCED TOOL USAGE!"""
        task_id = f"task_{int(time.time())}"
        start_time = time.time()
        
        logger.info(f"Executing: {command}")
        logger.info(f"Context received: {context}")
        
        try:
            # ⭐ CHECK IF WE CAN ANSWER DIRECTLY FROM CONTEXT (NO TOOLS!)
            should_answer, direct_answer = self._should_answer_from_context(command, context)
            if should_answer:
                logger.info("✅ Answering directly from context (no tools needed)")
                execution_time = time.time() - start_time
                result = {
                    "message": direct_answer,
                    "iterations": 0
                }
                self.db.save_task(task_id, command, "completed", result, None, execution_time)
                return {
                    "success": True,
                    "result": result,
                    "execution_time": execution_time
                }
            
            # Get tools from MCP
            tools_list = await self.mcp.get_tools_list()
            
            # Convert to Groq function format
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
            
            # ⭐ BUILD CONTEXT-AWARE PROMPT WITH WINDOWS INFO
            context_info = ""
            if context:
                # Include Windows context (folder, selected files)
                context_summary = {
                    'app': context.get('app', 'Unknown'),
                    'file': context.get('file', 'None'),
                    'window': context.get('window', 'None'),
                    'url': context.get('url', 'None'),
                    'currentFolder': context.get('currentFolder', 'None'),
                    'selectedFiles': len(context.get('selectedFiles', [])),
                    'selectedText': context.get('selectedText', 'None')[:200] if context.get('selectedText') else 'None',
                }
                
                context_info = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 CURRENT USER CONTEXT:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📱 Application: {context_summary['app']}
📄 File: {context_summary['file']}
🪟 Window: {context_summary['window']}
🌐 URL: {context_summary['url']}
📁 Folder: {context_summary['currentFolder']}
📋 Selected Files: {context_summary['selectedFiles']} file(s)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
            else:
                context_info = "⚠️  NO CONTEXT AVAILABLE"
            
            # ⭐ FORCED TOOL USAGE SYSTEM PROMPT
            messages = [
                {
                    "role": "system",
                    "content": f"""You are GodComet OS - a TOOL-USING AI assistant. You MUST use tools to perform actions.

{context_info}

🚨 CRITICAL RULES - YOU MUST FOLLOW THESE:

1. **YOU MUST USE TOOLS - NOT JUST TALK**
   ❌ WRONG: "I'll open the calculator for you" (just talking - NO ACTION)
   ✅ CORRECT: Actually call the launch_app tool with {{"app_name": "calculator"}}
   
   ❌ WRONG: "I can help you transfer files" (just offering - NO ACTION)
   ✅ CORRECT: Actually call the transfer_files tool with source and destination
   
   🚨 CRITICAL: When user asks you to DO something, you MUST call a tool immediately. DO NOT just explain what you would do.

2. **MANDATORY TOOL USAGE FOR ACTIONS:**
   These commands REQUIRE tool calls (not text responses):
   
   🖥️ WINDOWS AUTOMATION (ALWAYS USE TOOLS):
   - "open calculator" → MUST call launch_app({{"app_name": "calculator"}})
   - "open notepad" → MUST call launch_app({{"app_name": "notepad"}})
   - "launch chrome" → MUST call launch_app({{"app_name": "chrome"}})
   - "start vscode" → MUST call launch_app({{"app_name": "vscode"}})
   - "open file explorer" → MUST call launch_app({{"app_name": "file explorer"}})
   - "close calculator" → MUST call close_app({{"app_name": "calculator"}})
   - "close chrome" → MUST call close_app({{"app_name": "chrome"}})
   - "copy files from X to Y" → MUST call transfer_files({{"source": "X", "destination": "Y"}})
   - "move files from X to Y" → MUST call move_files({{"source": "X", "destination": "Y"}})
   - "show system info" → MUST call get_system_info()
   - "what apps are running" → MUST call get_running_apps()
   - "install WhatsApp" → MUST call install_app({{"app_name": "WhatsApp"}})
   - "open folder X" → MUST call open_folder({{"path": "X"}})
   - "create folder X" → MUST call create_folder({{"path": "X"}})
   
   📝 CODE ANALYSIS (ALWAYS USE TOOLS):
   - "analyze this code" → MUST call analyze_code with file path
   - "fix bugs" → MUST call fix_bugs with file path
   - "generate tests" → MUST call generate_tests with file path
   - "refactor code" → MUST call refactor_code with file path
   - "document code" → MUST call document_code with file path
   
   🌐 WEB & BROWSER (ALWAYS USE TOOLS):
   - "summarize article" → MUST call summarize_article
   - "scrape table" → MUST call scrape_table_to_csv
   - "research competitors" → MUST call research_competitors
   - "play youtube" → MUST call youtube_play
   - "navigate to X" → MUST call browser_navigate
   - "take screenshot" → MUST call browser_screenshot
   
   📂 FILES (ALWAYS USE TOOLS):
   - "list files" → MUST call list_directory
   - "read file X" → MUST call file_read
   - "write to file" → MUST call file_write
   
   🚀 GITHUB & DEPLOYMENT (ALWAYS USE TOOLS):
   - "create repo" → MUST call github_create_repo
   - "deploy to vercel" → MUST call vercel_deploy
   - "list deployments" → MUST call vercel_list_deployments

3. **ONLY ANSWER WITH TEXT (NO TOOLS) FOR:**
   - "what file am I editing?" → use context info above
   - "what app am I using?" → use context info above
   - Pure information questions with NO action needed

4. **WINDOWS PATH FORMAT:**
   Use double backslashes: C:\\\\Users\\\\tarun\\\\Downloads
   Common paths:
   - Downloads: C:\\\\Users\\\\tarun\\\\Downloads
   - Desktop: C:\\\\Users\\\\tarun\\\\Desktop
   - Documents: C:\\\\Users\\\\tarun\\\\Documents

5. **ERROR HANDLING:**
   - Don't repeat failed tools more than 2 times
   - If tool fails 2x with same error, STOP and report
   - Report errors clearly

🎯 REMEMBER: If user asks to DO something → USE THE TOOL. Don't just talk about it!

Available tools: {[t['function']['name'] for t in tools_for_groq]}"""
                },
                {
                    "role": "user",
                    "content": f"Execute this task: {command}"
                }
            ]
            
            # AI loop with function calling
            iteration = 0
            max_iterations = 10
            consecutive_failures = 0
            
            while iteration < max_iterations:
                iteration += 1
                logger.info(f"Groq iteration {iteration}/{max_iterations}")
                
                try:
                    # Call Groq API
                    response = self.client.chat.completions.create(
                        model="llama-3.1-8b-instant",
                        messages=messages,
                        tools=tools_for_groq,
                        tool_choice="auto",
                        temperature=0.1,
                        max_tokens=2048
                    )
                except Exception as api_error:
                    logger.error(f"Groq API error: {api_error}")
                    execution_time = time.time() - start_time
                    
                    if "413" in str(api_error) or "too large" in str(api_error).lower():
                        error_msg = "Request too large. Try a simpler command."
                    elif "429" in str(api_error) or "rate_limit" in str(api_error).lower():
                        error_msg = "Rate limit exceeded. Please wait a moment and try again."
                    else:
                        error_msg = f"API error: {str(api_error)}"
                    
                    self.db.save_task(task_id, command, "failed", None, error_msg, execution_time)
                    return {"success": False, "error": error_msg}
                
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
                            
                            # ⭐ CHECK FOR COMPLETION FLAG
                            if result.get("completed") is True:
                                logger.info("✅ Tool marked task as COMPLETED")
                                execution_time = time.time() - start_time
                                final_result = {
                                    "message": result.get("message", "Task completed"),
                                    "data": result.get("data", {}),
                                    "iterations": iteration
                                }
                                self.db.save_task(task_id, command, "completed", final_result, None, execution_time)
                                return {
                                    "success": True,
                                    "result": final_result,
                                    "execution_time": execution_time
                                }
                            
                            # ⭐ CHECK FOR FATAL ERROR
                            if result.get("fatal") is True:
                                logger.error("❌ Tool returned FATAL error")
                                execution_time = time.time() - start_time
                                error_msg = result.get("error", "Fatal error occurred")
                                self.db.save_task(task_id, command, "failed", None, error_msg, execution_time)
                                return {
                                    "success": False,
                                    "error": error_msg,
                                    "execution_time": execution_time
                                }
                            
                            # ⭐ DETECT REPEATED FAILURES
                            if not result.get("success"):
                                error_text = result.get('error', '').lower()
                                
                                # Check for encoding errors
                                if 'codec' in error_text or 'decode' in error_text or 'encoding' in error_text:
                                    consecutive_failures += 1
                                    
                                    if consecutive_failures >= 2:
                                        logger.error(f"❌ Encoding error {consecutive_failures} times - STOPPING")
                                        execution_time = time.time() - start_time
                                        error_msg = "Unable to read file due to encoding issues."
                                        self.db.save_task(task_id, command, "failed", None, error_msg, execution_time)
                                        return {
                                            "success": False,
                                            "error": error_msg,
                                            "execution_time": execution_time
                                        }
                                
                                # Check for browser errors
                                elif any(x in error_text for x in ['target page', 'browser has been closed', 'connection closed']):
                                    consecutive_failures += 1
                                    
                                    if consecutive_failures >= 3:
                                        logger.error("❌ Browser error 3 times - STOPPING")
                                        execution_time = time.time() - start_time
                                        error_msg = "Browser tool failed."
                                        self.db.save_task(task_id, command, "failed", None, error_msg, execution_time)
                                        return {
                                            "success": False,
                                            "error": error_msg,
                                            "execution_time": execution_time
                                        }
                                else:
                                    consecutive_failures = 0
                            else:
                                consecutive_failures = 0
                            
                            # Format result text (TRUNCATED)
                            if result.get("success"):
                                result_text = f"✅ {result.get('message', 'Success')}"
                                if result.get('data'):
                                    data = result['data']
                                    if 'vercel_url' in data and data['vercel_url']:
                                        result_text += f"\n🌐 LIVE: {data['vercel_url']}"
                                    if 'github_url' in data and data['github_url']:
                                        result_text += f"\n📦 GitHub: {data['github_url']}"
                                    if 'title' in data:
                                        result_text += f"\n▶️  {data['title']}"
                                    if 'url' in data and 'vercel_url' not in data:
                                        result_text += f"\n🔗 {data['url']}"
                                    if 'analysis' in data:
                                        result_text += f"\n📊 Analysis complete"
                                    if 'suggestions' in data:
                                        result_text += f"\n💡 Suggestions provided"
                                    if 'tests' in data:
                                        result_text += f"\n🧪 Tests generated"
                                    if 'refactored' in data:
                                        result_text += f"\n♻️  Refactoring complete"
                                    if 'documentation' in data:
                                        result_text += f"\n📝 Documentation generated"
                                    if 'summary' in data:
                                        result_text += f"\n📰 Article summarized"
                                    if 'results' in data:
                                        result_text += f"\n🔍 Found {len(data.get('results', []))} results"
                                # Limit to 500 chars
                                result_text = result_text[:500]
                            else:
                                result_text = f"❌ Error: {result.get('error', 'Unknown')}"
                            
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
                    
                    # Continue loop
                    continue
                
                else:
                    # AI is done
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
            
            # Max iterations
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
    
    async def chat(self, message: str, conversation_history: list = None) -> dict:
        """Simple chat without tools - used by code analysis and web scraping"""
        try:
            messages = conversation_history or []
            messages.append({"role": "user", "content": message})
            
            response = self.client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=messages,
                temperature=0.7,
                max_tokens=2048
            )
            
            reply = response.choices[0].message.content
            
            return {
                "success": True,
                "reply": reply,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                }
            }
            
        except Exception as e:
            logger.error(f"Chat failed: {e}")
            return {"success": False, "error": str(e)}