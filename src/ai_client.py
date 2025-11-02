"""AI Client with OpenAI"""
from openai import OpenAI
from .mcp_server import MCPServer
from .database import DatabaseManager
import time
import json
import logging

logger = logging.getLogger(__name__)

class AIClient:
    """AI client using OpenAI GPT-4o with MCP"""
    
    def __init__(self, api_key: str, mcp_server: MCPServer):
        self.client = OpenAI(api_key=api_key)
        self.mcp = mcp_server
        self.db = DatabaseManager()
        logger.info("OpenAI client initialized")
    
    async def execute(self, command: str) -> dict:
        """Execute command with AI"""
        task_id = f"task_{int(time.time())}"
        start_time = time.time()
        
        logger.info(f"Executing: {command}")
        
        try:
            # Get tools from MCP
            tools_list = await self.mcp.get_tools_list()
            
            # Convert to OpenAI function format
            tools_for_openai = []
            for t in tools_list:
                tools_for_openai.append({
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.inputSchema
                    }
                })
            
            logger.info(f"Available tools: {[t['function']['name'] for t in tools_for_openai]}")
            
            # Create messages
            messages = [
                {
                    "role": "system",
                    "content": "You are an AI automation assistant. Use the available tools to complete user tasks. Be thorough and provide clear feedback about what you're doing."
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
                logger.info(f"AI iteration {iteration}/{max_iterations}")
                
                # Call OpenAI
                response = self.client.chat.completions.create(
                    model="gpt-4o",
                    messages=messages,
                    tools=tools_for_openai,
                    tool_choice="auto",
                    temperature=0.1
                )
                
                assistant_message = response.choices[0].message
                logger.info(f"AI response - has tool calls: {bool(assistant_message.tool_calls)}")
                
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
                            
                            result_text = result[0].text if result else "Tool executed"
                            logger.info(f"Tool result: {result_text[:100]}")
                            
                            # Add tool result to messages
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": result_text
                            })
                        except Exception as e:
                            logger.error(f"Tool execution error: {e}")
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": f"Error: {str(e)}"
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