"""
GodComet Agentic OS - The Complete Platform
Unified system that detects context, suggests actions, and executes workflows autonomously
"""

import os
import asyncio
from typing import Dict, List, Optional
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from parent directory
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)
print(f"🔑 Loading environment from: {env_path}")

# Context system
from context.context_aggregator import ContextAggregator
from context.desktop_vision import DesktopVisionDetector
from context.action_registry import ActionRegistry, Action

# Verification system
from verification.visual_auditor import VisualAuditor
from verification.render_engine import RenderEngine
from verification.interactive_browser import InteractiveBrowser

# Tools
from tools.verified_figma_converter import VerifiedFigmaConverter


class AgenticOS:
    """
    The Complete Agentic Operating System

    Flow:
    1. User hits hotkey (Ctrl+Space)
    2. Detect context (VS Code, Chrome, Desktop, Clipboard)
    3. Analyze intent with Vision AI (optional desktop screenshot)
    4. Suggest relevant actions based on context
    5. Execute action(s) with autonomous verification
    6. Report results to user
    """

    def __init__(
        self,
        enable_vision: bool = True,
        enable_desktop_screenshot: bool = False,
        auto_suggest: bool = True
    ):
        """
        Initialize Agentic OS

        Args:
            enable_vision: Use Vision AI for analysis
            enable_desktop_screenshot: Take screenshots for context (slower)
            auto_suggest: Automatically suggest actions based on context
        """
        self.enable_vision = enable_vision
        self.enable_desktop_screenshot = enable_desktop_screenshot
        self.auto_suggest = auto_suggest

        # Initialize subsystems
        self.context_aggregator = ContextAggregator()
        self.desktop_vision = DesktopVisionDetector() if enable_vision else None
        self.action_registry = ActionRegistry()

        # Initialize tools
        self.verified_figma = VerifiedFigmaConverter()
        self.visual_auditor = VisualAuditor()
        self.render_engine = RenderEngine()

        # State
        self.last_context = None
        self.last_suggestions = []

    async def handle_hotkey(self, user_command: Optional[str] = None) -> Dict:
        """
        Handle hotkey activation

        Args:
            user_command: Optional explicit command from user
                          If None, will auto-suggest based on context

        Returns:
            {
                "context": {...},
                "suggestions": [...],
                "executed_action": "...",
                "result": {...}
            }
        """
        print("=" * 80)
        print("🚀 GODCOMET AGENTIC OS")
        print("=" * 80)

        # Step 1: Gather context
        print("\n📡 Gathering context...")
        context = await self.context_aggregator.get_unified_context()

        # Step 2: Enhance with vision (if enabled and no explicit command)
        if self.enable_desktop_screenshot and not user_command:
            print("👁️  Analyzing desktop with Vision AI...")
            vision_result = await self.desktop_vision.analyze_desktop()
            context = self.desktop_vision.enhance_context_with_vision(context, vision_result)

        self.last_context = context

        # Step 3: Determine action
        if user_command:
            # User provided explicit command
            action = await self._parse_user_command(user_command, context)
        elif self.auto_suggest:
            # Auto-suggest based on context
            suggestions = self.action_registry.get_available_actions(context)
            self.last_suggestions = suggestions

            if suggestions:
                print(f"\n💡 {len(suggestions)} actions available:")
                for i, action in enumerate(suggestions[:5], 1):  # Show top 5
                    print(f"   {i}. {action.name} - {action.description}")

                # Auto-execute the most relevant action
                action = suggestions[0]
                print(f"\n🎯 Auto-executing: {action.name}")
            else:
                return {
                    "context": context,
                    "suggestions": [],
                    "message": "No actions available for current context"
                }
        else:
            return {
                "context": context,
                "suggestions": self.action_registry.get_available_actions(context),
                "message": "Waiting for user command"
            }

        # Step 4: Execute action
        print(f"\n🚀 Executing: {action.name}")
        result = await self._execute_action(action, context)

        # Step 5: Return results
        return {
            "context": context,
            "suggestions": self.last_suggestions,
            "executed_action": action.id,
            "result": result
        }

    async def _parse_user_command(self, command: str, context: Dict) -> Action:
        """
        Parse user command to determine which action to execute

        Examples:
        - "deploy figma" → "generate_code_from_figma"
        - "fix errors" → "fix_console_errors"
        - "create pr" → "create_pull_request"
        """
        command_lower = command.lower()

        # Map common commands to actions
        command_map = {
            "deploy figma": "figma_to_production",
            "generate code": "generate_code_from_figma",
            "fix errors": "fix_console_errors",
            "create pr": "create_pull_request",
            "deploy": "deploy_to_vercel",
            "test": "visual_regression_test",
            "run tests": "run_tests"
        }

        # Find matching action
        for key, action_id in command_map.items():
            if key in command_lower:
                return self.action_registry.actions[action_id]

        # Fallback: search actions
        search_results = self.action_registry.search_actions(command)
        if search_results:
            return search_results[0]

        raise ValueError(f"Could not parse command: {command}")

    async def _execute_action(self, action: Action, context: Dict) -> Dict:
        """
        Execute an action based on its ID

        This routes to the appropriate handler (Figma converter, browser test, etc.)
        """
        action_id = action.id

        try:
            # DESIGN ACTIONS
            if action_id == "extract_figma_design":
                return await self._extract_figma(context)

            elif action_id == "generate_code_from_figma":
                return await self._generate_code_from_figma(context)

            elif action_id == "figma_to_production":
                return await self._figma_to_production(context)

            # DEBUG ACTIONS
            elif action_id == "fix_console_errors":
                return await self._fix_console_errors(context)

            # DEPLOY ACTIONS
            elif action_id == "deploy_to_vercel":
                return await self._deploy_to_vercel(context)

            elif action_id == "create_pull_request":
                return await self._create_pull_request(context)

            # TEST ACTIONS
            elif action_id == "visual_regression_test":
                return await self._visual_regression_test(context)

            else:
                return {
                    "success": False,
                    "error": f"Action {action_id} not implemented yet"
                }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    # ========================================================================
    # ACTION HANDLERS
    # ========================================================================

    async def _extract_figma(self, context: Dict) -> Dict:
        """Extract Figma design URL from context"""
        sources = context.get("sources", {})

        # Try clipboard
        clipboard = sources.get("clipboard", "")
        if "figma.com" in clipboard:
            return {"success": True, "figma_url": clipboard}

        # Try Chrome
        chrome = sources.get("chrome", {})
        if chrome and "figma.com" in chrome.get("url", ""):
            return {"success": True, "figma_url": chrome["url"]}

        return {"success": False, "error": "No Figma URL found in context"}

    async def _generate_code_from_figma(self, context: Dict) -> Dict:
        """Generate code from Figma URL"""
        # Extract Figma URL
        figma_result = await self._extract_figma(context)
        if not figma_result.get("success"):
            return figma_result

        figma_url = figma_result["figma_url"]

        # Use verified converter
        result = await self.verified_figma.run(
            figma_url=figma_url,
            github_create=False,  # Don't create repo yet
            vercel_deploy=False   # Don't deploy yet
        )

        return result

    async def _figma_to_production(self, context: Dict) -> Dict:
        """Full pipeline: Figma → Code → Verify → Deploy → PR"""
        # Extract Figma URL
        figma_result = await self._extract_figma(context)
        if not figma_result.get("success"):
            return figma_result

        figma_url = figma_result["figma_url"]

        # Use verified converter (full pipeline)
        result = await self.verified_figma.run(
            figma_url=figma_url,
            github_create=True,   # Create repo
            vercel_deploy=True    # Deploy
        )

        return result

    async def _fix_console_errors(self, context: Dict) -> Dict:
        """Fix console errors detected in Chrome"""
        sources = context.get("sources", {})
        chrome = sources.get("chrome", {})

        if not chrome or not chrome.get("console_errors"):
            return {"success": False, "error": "No console errors detected"}

        errors = chrome["console_errors"]
        vscode = sources.get("vscode", {})
        current_file = vscode.get("file")

        return {
            "success": True,
            "errors": errors,
            "current_file": current_file,
            "message": f"Detected {len(errors)} console errors",
            "note": "Error fixing implementation pending"
        }

    async def _deploy_to_vercel(self, context: Dict) -> Dict:
        """Deploy current project to Vercel"""
        sources = context.get("sources", {})
        vscode = sources.get("vscode", {})
        project_root = vscode.get("project_root")

        if not project_root:
            return {"success": False, "error": "No project root found"}

        # TODO: Integrate with Vercel tool
        return {
            "success": True,
            "project_root": project_root,
            "note": "Vercel deployment implementation pending"
        }

    async def _create_pull_request(self, context: Dict) -> Dict:
        """Create PR on GitHub"""
        sources = context.get("sources", {})
        vscode = sources.get("vscode", {})
        git_branch = vscode.get("git_branch")

        if not git_branch:
            return {"success": False, "error": "No git branch found"}

        # TODO: Integrate with GitHub tool
        return {
            "success": True,
            "branch": git_branch,
            "note": "PR creation implementation pending"
        }

    async def _visual_regression_test(self, context: Dict) -> Dict:
        """Run visual regression test"""
        sources = context.get("sources", {})

        # Need Figma URL and localhost URL
        figma_result = await self._extract_figma(context)
        chrome = sources.get("chrome", {})

        if not figma_result.get("success"):
            return {"success": False, "error": "No Figma URL for comparison"}

        if not chrome or "localhost" not in chrome.get("url", ""):
            return {"success": False, "error": "No localhost URL detected"}

        # TODO: Implement visual regression test
        return {
            "success": True,
            "figma_url": figma_result["figma_url"],
            "localhost_url": chrome["url"],
            "note": "Visual regression test implementation pending"
        }

    # ========================================================================
    # UTILITY METHODS
    # ========================================================================

    def get_context_summary(self) -> str:
        """Get human-readable context summary"""
        if not self.last_context:
            return "No context available"

        return self.context_aggregator.get_context_summary()

    def get_available_actions(self) -> List[Action]:
        """Get list of currently available actions"""
        if not self.last_context:
            return []

        return self.action_registry.get_available_actions(self.last_context)


# ============================================================================
# CLI INTERFACE
# ============================================================================

async def main():
    """CLI entry point for testing"""
    import sys

    print("🚀 GodComet Agentic OS - Interactive Mode\n")

    os = AgenticOS(
        enable_vision=True,
        enable_desktop_screenshot=False,  # Disable for speed
        auto_suggest=True
    )

    if len(sys.argv) > 1:
        # Execute specific command
        command = " ".join(sys.argv[1:])
        print(f"Executing command: {command}\n")
        result = await os.handle_hotkey(command)
        print("\n" + "=" * 80)
        print("RESULT:")
        print("=" * 80)
        import json
        print(json.dumps(result, indent=2, default=str))
    else:
        # Interactive mode
        print("No command provided, analyzing context...\n")
        result = await os.handle_hotkey()

        print("\n" + "=" * 80)
        print("CONTEXT SUMMARY:")
        print("=" * 80)
        print(os.get_context_summary())

        print("\n" + "=" * 80)
        print("AVAILABLE ACTIONS:")
        print("=" * 80)
        actions = os.get_available_actions()
        if actions:
            for i, action in enumerate(actions, 1):
                print(f"{i}. {action.name}")
                print(f"   {action.description}")
        else:
            print("No actions available for current context")


if __name__ == "__main__":
    asyncio.run(main())
