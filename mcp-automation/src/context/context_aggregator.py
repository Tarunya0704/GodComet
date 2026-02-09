"""
Context Aggregator - The Central Brain
Polls VS Code, Chrome, Desktop, and Clipboard for unified context
"""

import os
import json
import asyncio
import subprocess
from typing import Dict, List, Optional
from datetime import datetime
from pathlib import Path


class ContextAggregator:
    """
    Aggregates context from multiple sources:
    - VS Code (current file, selection, git branch)
    - Chrome (active tab URL, console errors)
    - Desktop (active window, screenshot)
    - Clipboard (recent copy)
    - File System (current project structure)
    """

    def __init__(
        self,
        vscode_enabled: bool = True,
        chrome_enabled: bool = True,
        desktop_enabled: bool = True,
        clipboard_enabled: bool = True
    ):
        self.vscode_enabled = vscode_enabled
        self.chrome_enabled = chrome_enabled
        self.desktop_enabled = desktop_enabled
        self.clipboard_enabled = clipboard_enabled

        self.last_context = {}
        self.context_history = []

    async def get_unified_context(self) -> Dict:
        """
        Get unified context from all sources

        Returns:
            {
                "timestamp": "2026-01-28T14:30:22",
                "vscode": {...},
                "chrome": {...},
                "desktop": {...},
                "clipboard": "...",
                "intent": "user is working on Auth component in Figma",
                "recommended_actions": [...]
            }
        """
        print("🧠 Aggregating context from all sources...")

        context = {
            "timestamp": datetime.now().isoformat(),
            "sources": {}
        }

        # Gather context in parallel
        tasks = []

        if self.vscode_enabled:
            tasks.append(self._get_vscode_context())
        if self.chrome_enabled:
            tasks.append(self._get_chrome_context())
        if self.desktop_enabled:
            tasks.append(self._get_desktop_context())
        if self.clipboard_enabled:
            tasks.append(self._get_clipboard_context())

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Map results to context
        if self.vscode_enabled:
            context["sources"]["vscode"] = results[0] if not isinstance(results[0], Exception) else None
        if self.chrome_enabled:
            idx = 1 if self.vscode_enabled else 0
            context["sources"]["chrome"] = results[idx] if not isinstance(results[idx], Exception) else None
        if self.desktop_enabled:
            idx = (1 if self.vscode_enabled else 0) + (1 if self.chrome_enabled else 0)
            context["sources"]["desktop"] = results[idx] if not isinstance(results[idx], Exception) else None
        if self.clipboard_enabled:
            idx = (1 if self.vscode_enabled else 0) + (1 if self.chrome_enabled else 0) + (1 if self.desktop_enabled else 0)
            context["sources"]["clipboard"] = results[idx] if not isinstance(results[idx], Exception) else None

        # Analyze intent
        context["intent"] = self._analyze_intent(context["sources"])
        context["recommended_actions"] = self._suggest_actions(context)

        # Store in history
        self.last_context = context
        self.context_history.append(context)

        # Limit history to 10 entries
        if len(self.context_history) > 10:
            self.context_history.pop(0)

        print(f"   ✅ Context aggregated: {len(context['sources'])} sources")
        return context

    async def _get_vscode_context(self) -> Optional[Dict]:
        """Get context from VS Code extension via WebSocket"""
        try:
            # In production, this would connect to the VS Code extension WebSocket
            # For now, we'll read from a shared state file if it exists

            vscode_state_file = Path.home() / ".godcomet" / "vscode_state.json"
            if vscode_state_file.exists():
                with open(vscode_state_file, "r") as f:
                    state = json.load(f)
                    return {
                        "active": True,
                        "file": state.get("activeFile"),
                        "language": state.get("language"),
                        "selection": state.get("selection"),
                        "git_branch": state.get("gitBranch"),
                        "project_root": state.get("workspaceRoot"),
                        "cursor_position": state.get("cursorPosition")
                    }
            else:
                return {"active": False, "note": "VS Code extension not connected"}

        except Exception as e:
            print(f"   ⚠️  VS Code context error: {e}")
            return None

    async def _get_chrome_context(self) -> Optional[Dict]:
        """Get context from Chrome extension via WebSocket"""
        try:
            # Similar to VS Code, read from shared state file
            chrome_state_file = Path.home() / ".godcomet" / "chrome_state.json"
            if chrome_state_file.exists():
                with open(chrome_state_file, "r") as f:
                    state = json.load(f)
                    return {
                        "active": True,
                        "url": state.get("url"),
                        "title": state.get("title"),
                        "console_errors": state.get("consoleErrors", []),
                        "dom_summary": state.get("domSummary")
                    }
            else:
                return {"active": False, "note": "Chrome extension not connected"}

        except Exception as e:
            print(f"   ⚠️  Chrome context error: {e}")
            return None

    async def _get_desktop_context(self) -> Optional[Dict]:
        """Get context from desktop (active window, screenshot)"""
        try:
            # Detect active window
            active_window = await self._detect_active_window()

            context = {
                "active_window": active_window,
                "os": os.name,
                "platform": subprocess.check_output(
                    ["uname", "-s"] if os.name != "nt" else ["cmd", "/c", "ver"],
                    text=True,
                    stderr=subprocess.DEVNULL
                ).strip()
            }

            # Optional: Take screenshot for vision analysis
            # This would be used when user hits hotkey
            # context["screenshot_path"] = await self._take_screenshot()

            return context

        except Exception as e:
            print(f"   ⚠️  Desktop context error: {e}")
            return None

    async def _detect_active_window(self) -> Optional[str]:
        """Detect the currently active window"""
        try:
            if os.name == "nt":  # Windows
                result = subprocess.check_output(
                    [
                        "powershell",
                        "-Command",
                        "Add-Type -AssemblyName System.Windows.Forms; "
                        "[System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea; "
                        "(Get-Process | Where-Object {$_.MainWindowTitle -ne ''} | "
                        "Select-Object -First 1).MainWindowTitle"
                    ],
                    text=True,
                    stderr=subprocess.DEVNULL
                )
                return result.strip()
            else:  # macOS/Linux
                result = subprocess.check_output(
                    ["osascript", "-e", 'tell application "System Events" to get name of first application process whose frontmost is true'],
                    text=True,
                    stderr=subprocess.DEVNULL
                )
                return result.strip()

        except Exception as e:
            print(f"   ⚠️  Active window detection failed: {e}")
            return None

    async def _get_clipboard_context(self) -> Optional[str]:
        """Get clipboard content"""
        try:
            if os.name == "nt":  # Windows
                result = subprocess.check_output(
                    ["powershell", "-Command", "Get-Clipboard"],
                    text=True,
                    stderr=subprocess.DEVNULL
                )
                return result.strip()
            else:  # macOS
                result = subprocess.check_output(
                    ["pbpaste"],
                    text=True,
                    stderr=subprocess.DEVNULL
                )
                return result.strip()

        except Exception as e:
            print(f"   ⚠️  Clipboard read failed: {e}")
            return None

    def _analyze_intent(self, sources: Dict) -> str:
        """
        Analyze context to determine user intent

        Examples:
        - "Working on Auth.tsx in VS Code, has Figma URL in clipboard → wants to implement design"
        - "Chrome shows console error, VS Code open → wants to debug"
        - "Figma is active window → wants to extract design"
        """
        intent_signals = []

        # VS Code context
        vscode = sources.get("vscode", {})
        if vscode and vscode.get("active"):
            file_name = vscode.get("file", "").split("/")[-1]
            if file_name:
                intent_signals.append(f"editing {file_name}")

        # Chrome context
        chrome = sources.get("chrome", {})
        if chrome and chrome.get("active"):
            url = chrome.get("url", "")
            if "figma.com" in url:
                intent_signals.append("viewing Figma design")
            elif "vercel.app" in url or "localhost" in url:
                intent_signals.append("testing deployment")

            if chrome.get("console_errors"):
                intent_signals.append(f"{len(chrome['console_errors'])} console errors")

        # Desktop context
        desktop = sources.get("desktop", {})
        if desktop:
            active_window = desktop.get("active_window", "")
            if "Figma" in active_window:
                intent_signals.append("Figma is active")
            elif "Code" in active_window:
                intent_signals.append("VS Code is active")

        # Clipboard context
        clipboard = sources.get("clipboard", "")
        if clipboard and "figma.com" in clipboard:
            intent_signals.append("has Figma URL in clipboard")

        if intent_signals:
            return "User is " + ", ".join(intent_signals)
        else:
            return "Unknown intent - waiting for user command"

    def _suggest_actions(self, context: Dict) -> List[str]:
        """
        Suggest relevant actions based on context

        Returns list of action IDs that can be executed
        """
        suggestions = []
        sources = context.get("sources", {})

        # Figma-related actions
        chrome = sources.get("chrome", {})
        clipboard = sources.get("clipboard", "")

        if chrome and "figma.com" in chrome.get("url", ""):
            suggestions.append("extract_figma_design")
            suggestions.append("generate_code_from_figma")

        if clipboard and "figma.com" in clipboard:
            suggestions.append("extract_figma_from_clipboard")

        # Debugging actions
        if chrome and chrome.get("console_errors"):
            suggestions.append("fix_console_errors")

        # Deployment actions
        vscode = sources.get("vscode", {})
        if vscode and vscode.get("git_branch"):
            suggestions.append("deploy_to_vercel")
            suggestions.append("create_pull_request")

        return suggestions

    def get_context_summary(self) -> str:
        """
        Get human-readable context summary for AI prompt
        """
        if not self.last_context:
            return "No context available."

        sources = self.last_context.get("sources", {})
        lines = []

        # VS Code
        vscode = sources.get("vscode", {})
        if vscode and vscode.get("active"):
            file = vscode.get("file", "unknown")
            branch = vscode.get("git_branch", "unknown")
            lines.append(f"📝 VS Code: Editing {file} (branch: {branch})")

        # Chrome
        chrome = sources.get("chrome", {})
        if chrome and chrome.get("active"):
            url = chrome.get("url", "unknown")
            lines.append(f"🌐 Chrome: Viewing {url}")
            if chrome.get("console_errors"):
                lines.append(f"   ⚠️  {len(chrome['console_errors'])} console errors")

        # Desktop
        desktop = sources.get("desktop", {})
        if desktop:
            window = desktop.get("active_window", "unknown")
            lines.append(f"🖥️  Active: {window}")

        # Clipboard
        clipboard = sources.get("clipboard", "")
        if clipboard and len(clipboard) < 100:
            lines.append(f"📋 Clipboard: {clipboard}")

        # Intent
        intent = self.last_context.get("intent", "")
        if intent:
            lines.append(f"\n💡 Intent: {intent}")

        # Suggestions
        suggestions = self.last_context.get("recommended_actions", [])
        if suggestions:
            lines.append(f"🎯 Suggested actions: {', '.join(suggestions)}")

        return "\n".join(lines)


# Standalone test
async def test_context_aggregator():
    """Test context aggregation"""
    print("🧪 Testing Context Aggregator\n")

    aggregator = ContextAggregator()

    # Get context
    context = await aggregator.get_unified_context()

    print("\n📊 Unified Context:")
    print(json.dumps(context, indent=2, default=str))

    print("\n📝 Human-Readable Summary:")
    print(aggregator.get_context_summary())


if __name__ == "__main__":
    asyncio.run(test_context_aggregator())
