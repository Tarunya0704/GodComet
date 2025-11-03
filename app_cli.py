#!/usr/bin/env python3
"""CLI Application - Main Entry Point"""
import asyncio
import os
import sys
from src.config import Config
from src.mcp_server import MCPServer
from src.ai_client import AIClient

async def main():
    print("=" * 60)
    print("  ⚡ MCP AI Automation System - Groq AI")
    print("  🚀 Ultra-Fast AI Inference")
    print("=" * 60)
    print()
    
    # Validate config
    try:
        Config.validate()
        print("✅ Groq API key loaded")
    except ValueError as e:
        print(f"❌ Configuration error: {e}")
        print("\nPlease create a .env file with:")
        print("GROQ_API_KEY=gsk_your-key-here")
        print("\nGet your key from: https://console.groq.com/")
        return
    
    # Initialize
    print("🔧 Initializing MCP server...")
    mcp = MCPServer()
    
    if Config.AWS_ACCESS_KEY_ID and Config.AWS_SECRET_ACCESS_KEY:
        mcp.configure_aws(
            Config.AWS_ACCESS_KEY_ID,
            Config.AWS_SECRET_ACCESS_KEY,
            Config.AWS_REGION
        )
        print(f"✅ AWS configured (region: {Config.AWS_REGION})")
    else:
        print("⚠️  AWS not configured (optional)")
    
    print("⚡ Initializing AI client with Groq (ultra-fast)...")
    ai = AIClient(Config.GROQ_API_KEY, mcp)
    print("✅ System ready!")
    print()
    
    print("💡 Example commands:")
    print("   • play music on youtube")
    print("   • create s3 bucket test-bucket-2024")
    print("   • go to google.com")
    print("   • list files")
    print()
    print("💨 Groq is 10x faster than OpenAI!")
    print("Commands: 'quit' or 'exit' to stop, 'history' for past tasks")
    print("=" * 60)
    print()
    
    while True:
        try:
            command = input("⚡ Groq Command: ").strip()
            
            if not command:
                continue
            
            if command.lower() in ['quit', 'exit', 'q']:
                print("\n👋 Goodbye!")
                await mcp.browser.close()
                break
            
            if command.lower() == 'history':
                print("\n📋 Recent Tasks:")
                print("-" * 60)
                tasks = mcp.db.get_recent_tasks(10)
                for task in tasks:
                    status_icon = "✅" if task[3] == "completed" else "❌"
                    print(f"{status_icon} [{task[6][:19]}] {task[1][:50]}")
                print("-" * 60)
                print()
                continue
            
            print(f"\n▶️  Executing: {command}")
            print("⚡ Groq is processing at lightning speed...\n")
            
            result = await ai.execute(command)
            
            print("\n" + "=" * 60)
            if result["success"]:
                print("✅ Success!")
                print(f"\n{result['result']['message']}")
                print(f"\n📊 AI Iterations: {result['result']['iterations']}")
                print(f"⏱️  Time: {result['execution_time']:.2f}s ⚡")
            else:
                print("❌ Failed!")
                print(f"\nError: {result['error']}")
            print("=" * 60)
            print()
            
        except KeyboardInterrupt:
            print("\n\n👋 Interrupted!")
            await mcp.browser.close()
            break
        except Exception as e:
            print(f"\n❌ Error: {e}\n")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")