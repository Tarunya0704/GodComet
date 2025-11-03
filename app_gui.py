#!/usr/bin/env python3
"""GUI Application - Main Entry Point"""
import tkinter as tk
from tkinter import scrolledtext, messagebox
import asyncio
import threading
from datetime import datetime
from src.config import Config
from src.mcp_server import MCPServer
from src.ai_client import AIClient

class AutomationGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("⚡ MCP AI Automation - Groq")
        self.root.geometry("1000x700")
        self.root.configure(bg='#1e1e2e')
        
        self.mcp = None
        self.ai = None
        self.loop = None
        self.is_executing = False
        
        self.setup_gui()
        self.setup_async()
        self.initialize_system()
    
    def setup_gui(self):
        # Header
        header = tk.Label(
            self.root,
            text="⚡ MCP AI Automation - Groq",
            font=("Helvetica", 24, "bold"),
            bg='#1e1e2e',
            fg='#58a6ff'
        )
        header.pack(pady=20)
        
        # Subtitle
        subtitle = tk.Label(
            self.root,
            text="🚀 Ultra-Fast AI Inference",
            font=("Helvetica", 12),
            bg='#1e1e2e',
            fg='#3fb950'
        )
        subtitle.pack(pady=(0, 20))
        
        # Command input
        tk.Label(
            self.root,
            text="Enter Command:",
            font=("Helvetica", 12),
            bg='#1e1e2e',
            fg='#c9d1d9'
        ).pack(anchor=tk.W, padx=20)
        
        self.command_text = tk.Text(
            self.root,
            height=3,
            font=("Helvetica", 11),
            bg='#0d1117',
            fg='#c9d1d9',
            padx=10,
            pady=10
        )
        self.command_text.pack(fill=tk.X, padx=20, pady=10)
        
        # Execute button
        self.execute_btn = tk.Button(
            self.root,
            text="⚡ Execute Command",
            command=self.execute_command_threaded,
            bg='#58a6ff',
            fg='white',
            font=("Helvetica", 12, "bold"),
            padx=20,
            pady=10,
            cursor="hand2"
        )
        self.execute_btn.pack(pady=10)
        
        # Output
        tk.Label(
            self.root,
            text="Output:",
            font=("Helvetica", 12),
            bg='#1e1e2e',
            fg='#c9d1d9'
        ).pack(anchor=tk.W, padx=20, pady=(20, 5))
        
        self.output_text = scrolledtext.ScrolledText(
            self.root,
            height=20,
            font=("Consolas", 10),
            bg='#0d1117',
            fg='#3fb950',
            padx=15,
            pady=15
        )
        self.output_text.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 20))
    
    def setup_async(self):
        self.loop = asyncio.new_event_loop()
        
        def run_loop():
            asyncio.set_event_loop(self.loop)
            self.loop.run_forever()
        
        thread = threading.Thread(target=run_loop, daemon=True)
        thread.start()
    
    def initialize_system(self):
        try:
            Config.validate()
            
            self.log("🔧 Initializing MCP server...")
            self.mcp = MCPServer()
            
            if Config.AWS_ACCESS_KEY_ID and Config.AWS_SECRET_ACCESS_KEY:
                self.mcp.configure_aws(
                    Config.AWS_ACCESS_KEY_ID,
                    Config.AWS_SECRET_ACCESS_KEY,
                    Config.AWS_REGION
                )
                self.log("✅ AWS configured")
            
            self.log("⚡ Initializing AI client with Groq...")
            # FIXED: Using GROQ_API_KEY from Config
            self.ai = AIClient(Config.GROQ_API_KEY, self.mcp)
            self.log("✅ System ready!")
            self.log("💡 Try: 'play god's plan on youtube'")
            self.log("💨 Groq is 10x faster than OpenAI!\n")
            
        except ValueError as e:
            self.log(f"❌ Configuration error: {e}")
            self.log("Please configure .env file with your GROQ_API_KEY")
            messagebox.showerror("Configuration Error", str(e))
    
    def log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.output_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.output_text.see(tk.END)
        self.root.update()
    
    def execute_command_threaded(self):
        if self.is_executing:
            self.log("⚠️ Task already running!")
            return
        
        command = self.command_text.get("1.0", tk.END).strip()
        if not command:
            self.log("⚠️ Enter a command first!")
            return
        
        if not self.ai:
            self.log("❌ System not initialized!")
            return
        
        thread = threading.Thread(target=self.execute_command, args=(command,))
        thread.daemon = True
        thread.start()
    
    def execute_command(self, command: str):
        self.is_executing = True
        self.execute_btn.config(state=tk.DISABLED, text="⏳ Executing...")
        
        try:
            self.log(f"▶️ Executing: {command}")
            self.log("⚡ Groq is processing at lightning speed...\n")
            
            future = asyncio.run_coroutine_threadsafe(
                self.ai.execute(command),
                self.loop
            )
            result = future.result(timeout=300)
            
            self.log("=" * 60)
            if result["success"]:
                self.log("✅ Success!")
                self.log(f"\n{result['result']['message']}")
                self.log(f"\n📊 AI Iterations: {result['result']['iterations']}")
                self.log(f"⏱️  Time: {result['execution_time']:.2f}s ⚡")
            else:
                self.log("❌ Failed!")
                self.log(f"\nError: {result['error']}")
            self.log("=" * 60 + "\n")
            
            self.command_text.delete("1.0", tk.END)
            
        except Exception as e:
            self.log(f"❌ Error: {str(e)}")
        finally:
            self.is_executing = False
            self.execute_btn.config(state=tk.NORMAL, text="⚡ Execute Command")

def main():
    root = tk.Tk()
    app = AutomationGUI(root)
    
    def on_closing():
        if messagebox.askokcancel("Quit", "Exit application?"):
            if app.loop:
                app.loop.call_soon_threadsafe(app.loop.stop)
            root.destroy()
    
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()