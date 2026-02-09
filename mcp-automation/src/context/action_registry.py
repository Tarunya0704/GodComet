"""
Action Registry - Library of cross-app workflows
Defines actions the AI can execute based on context
"""

import asyncio
from typing import Dict, List, Callable, Optional
from dataclasses import dataclass
from enum import Enum


class ActionCategory(Enum):
    """Categories of actions"""
    DESIGN = "design"
    CODE = "code"
    DEBUG = "debug"
    DEPLOY = "deploy"
    TEST = "test"
    WORKFLOW = "workflow"


@dataclass
class Action:
    """
    Represents an executable action
    """
    id: str
    name: str
    description: str
    category: ActionCategory
    required_context: List[str]  # e.g., ["vscode", "figma_url"]
    handler: Optional[Callable] = None
    parameters: Optional[Dict] = None


class ActionRegistry:
    """
    Central registry of all available actions
    Maps context → actions → execution
    """

    def __init__(self):
        self.actions: Dict[str, Action] = {}
        self._register_builtin_actions()

    def _register_builtin_actions(self):
        """Register all built-in actions"""

        # DESIGN ACTIONS
        self.register(Action(
            id="extract_figma_design",
            name="Extract Figma Design",
            description="Extract design from active Figma tab",
            category=ActionCategory.DESIGN,
            required_context=["chrome_url_contains_figma"]
        ))

        self.register(Action(
            id="extract_figma_from_clipboard",
            name="Extract Figma from Clipboard",
            description="Extract design from Figma URL in clipboard",
            category=ActionCategory.DESIGN,
            required_context=["clipboard_contains_figma"]
        ))

        self.register(Action(
            id="generate_code_from_figma",
            name="Generate Code from Figma",
            description="Convert Figma design to React/Next.js code with visual verification",
            category=ActionCategory.CODE,
            required_context=["figma_url"]
        ))

        # CODE ACTIONS
        self.register(Action(
            id="implement_component",
            name="Implement Component",
            description="Generate code for a specific component based on Figma",
            category=ActionCategory.CODE,
            required_context=["vscode_active", "figma_url"]
        ))

        self.register(Action(
            id="refactor_code",
            name="Refactor Code",
            description="Refactor the currently open file in VS Code",
            category=ActionCategory.CODE,
            required_context=["vscode_active", "vscode_file"]
        ))

        # DEBUG ACTIONS
        self.register(Action(
            id="fix_console_errors",
            name="Fix Console Errors",
            description="Analyze and fix console errors in Chrome",
            category=ActionCategory.DEBUG,
            required_context=["chrome_console_errors", "vscode_active"]
        ))

        self.register(Action(
            id="debug_deployment",
            name="Debug Deployment",
            description="Investigate deployment errors and suggest fixes",
            category=ActionCategory.DEBUG,
            required_context=["chrome_url_contains_vercel"]
        ))

        # DEPLOY ACTIONS
        self.register(Action(
            id="deploy_to_vercel",
            name="Deploy to Vercel",
            description="Deploy current project to Vercel",
            category=ActionCategory.DEPLOY,
            required_context=["vscode_active", "vscode_project_root"]
        ))

        self.register(Action(
            id="create_pull_request",
            name="Create Pull Request",
            description="Create a PR on GitHub with current changes",
            category=ActionCategory.DEPLOY,
            required_context=["vscode_git_branch"]
        ))

        self.register(Action(
            id="create_github_repo",
            name="Create GitHub Repository",
            description="Create a new GitHub repo and push current project",
            category=ActionCategory.DEPLOY,
            required_context=["vscode_project_root"]
        ))

        # TEST ACTIONS
        self.register(Action(
            id="run_tests",
            name="Run Tests",
            description="Run test suite in current project",
            category=ActionCategory.TEST,
            required_context=["vscode_project_root"]
        ))

        self.register(Action(
            id="visual_regression_test",
            name="Visual Regression Test",
            description="Compare current UI to Figma design",
            category=ActionCategory.TEST,
            required_context=["figma_url", "chrome_localhost"]
        ))

        # WORKFLOW ACTIONS (Multi-step)
        self.register(Action(
            id="figma_to_production",
            name="Figma to Production (Full Pipeline)",
            description="Extract Figma → Generate Code → Verify → Deploy → Create PR",
            category=ActionCategory.WORKFLOW,
            required_context=["figma_url"]
        ))

        self.register(Action(
            id="fix_and_deploy",
            name="Fix Errors and Deploy",
            description="Fix console errors → Run tests → Deploy if passing",
            category=ActionCategory.WORKFLOW,
            required_context=["chrome_console_errors", "vscode_active"]
        ))

        self.register(Action(
            id="screenshot_to_jira",
            name="Screenshot to Jira",
            description="Take screenshot of bug → Create Jira ticket with details",
            category=ActionCategory.WORKFLOW,
            required_context=["desktop_screenshot"]
        ))

    def register(self, action: Action):
        """Register a new action"""
        self.actions[action.id] = action

    def get_available_actions(self, context: Dict) -> List[Action]:
        """
        Get list of actions available based on current context

        Args:
            context: Unified context from ContextAggregator

        Returns:
            List of Action objects that can be executed
        """
        available = []

        for action in self.actions.values():
            if self._check_context_requirements(action, context):
                available.append(action)

        return available

    def _check_context_requirements(self, action: Action, context: Dict) -> bool:
        """Check if context satisfies action requirements"""
        sources = context.get("sources", {})

        for requirement in action.required_context:
            if not self._check_single_requirement(requirement, sources, context):
                return False

        return True

    def _check_single_requirement(self, requirement: str, sources: Dict, full_context: Dict) -> bool:
        """Check a single context requirement"""

        # VS Code requirements
        if requirement == "vscode_active":
            return sources.get("vscode", {}).get("active", False)
        elif requirement == "vscode_file":
            return bool(sources.get("vscode", {}).get("file"))
        elif requirement == "vscode_project_root":
            return bool(sources.get("vscode", {}).get("project_root"))
        elif requirement == "vscode_git_branch":
            return bool(sources.get("vscode", {}).get("git_branch"))

        # Chrome requirements
        elif requirement == "chrome_console_errors":
            return len(sources.get("chrome", {}).get("console_errors", [])) > 0
        elif requirement == "chrome_url_contains_figma":
            url = sources.get("chrome", {}).get("url", "")
            return "figma.com" in url
        elif requirement == "chrome_url_contains_vercel":
            url = sources.get("chrome", {}).get("url", "")
            return "vercel.app" in url
        elif requirement == "chrome_localhost":
            url = sources.get("chrome", {}).get("url", "")
            return "localhost" in url

        # Clipboard requirements
        elif requirement == "clipboard_contains_figma":
            clipboard = sources.get("clipboard", "")
            return "figma.com" in clipboard

        # Figma URL (from any source)
        elif requirement == "figma_url":
            # Check clipboard
            clipboard = sources.get("clipboard", "")
            if "figma.com" in clipboard:
                return True
            # Check Chrome
            url = sources.get("chrome", {}).get("url", "")
            if "figma.com" in url:
                return True
            return False

        # Desktop requirements
        elif requirement == "desktop_screenshot":
            return True  # Can always take a screenshot

        return False

    async def execute_action(self, action_id: str, context: Dict) -> Dict:
        """
        Execute an action

        Returns:
            {
                "success": True/False,
                "result": {...},
                "error": "..." (if failed)
            }
        """
        action = self.actions.get(action_id)
        if not action:
            return {"success": False, "error": f"Action {action_id} not found"}

        # Check context requirements
        if not self._check_context_requirements(action, context):
            return {
                "success": False,
                "error": f"Context requirements not met for {action_id}",
                "required": action.required_context
            }

        print(f"🚀 Executing action: {action.name}")

        # Execute handler if available
        if action.handler:
            try:
                result = await action.handler(context)
                return {"success": True, "result": result}
            except Exception as e:
                return {"success": False, "error": str(e)}
        else:
            # Action needs to be implemented
            return {
                "success": False,
                "error": f"Action {action_id} has no handler implemented",
                "note": "This action is defined but needs implementation"
            }

    def get_action_chain(self, workflow_id: str) -> List[str]:
        """
        Get the sequence of actions for a workflow

        For example, "figma_to_production" returns:
        ["extract_figma_design", "generate_code_from_figma", "visual_regression_test", "deploy_to_vercel", "create_pull_request"]
        """
        workflows = {
            "figma_to_production": [
                "extract_figma_design",
                "generate_code_from_figma",
                "visual_regression_test",
                "deploy_to_vercel",
                "create_github_repo"
            ],
            "fix_and_deploy": [
                "fix_console_errors",
                "run_tests",
                "deploy_to_vercel"
            ],
            "screenshot_to_jira": [
                "desktop_screenshot",
                "create_jira_ticket"
            ]
        }

        return workflows.get(workflow_id, [])

    def get_actions_by_category(self, category: ActionCategory) -> List[Action]:
        """Get all actions in a category"""
        return [a for a in self.actions.values() if a.category == category]

    def search_actions(self, query: str) -> List[Action]:
        """Search actions by name or description"""
        query_lower = query.lower()
        results = []

        for action in self.actions.values():
            if (query_lower in action.name.lower() or
                query_lower in action.description.lower() or
                query_lower in action.id.lower()):
                results.append(action)

        return results


# Standalone test
def test_action_registry():
    """Test action registry"""
    print("🧪 Testing Action Registry\n")

    registry = ActionRegistry()

    # Test 1: List all actions
    print(f"📋 Registered Actions: {len(registry.actions)}")
    for action in registry.actions.values():
        print(f"   - {action.name} ({action.category.value})")

    # Test 2: Check available actions based on context
    print("\n🔍 Testing Context Matching:")

    # Scenario 1: User has Figma URL in clipboard
    context1 = {
        "sources": {
            "clipboard": "https://figma.com/file/abc123",
            "vscode": {"active": False},
            "chrome": {"active": False}
        }
    }
    available1 = registry.get_available_actions(context1)
    print(f"\n   Scenario 1: Figma URL in clipboard")
    print(f"   Available actions: {[a.name for a in available1]}")

    # Scenario 2: User has VS Code open with console errors in Chrome
    context2 = {
        "sources": {
            "vscode": {"active": True, "file": "App.tsx", "project_root": "/project"},
            "chrome": {"active": True, "url": "http://localhost:3000", "console_errors": ["TypeError: undefined"]}
        }
    }
    available2 = registry.get_available_actions(context2)
    print(f"\n   Scenario 2: VS Code + Console Errors")
    print(f"   Available actions: {[a.name for a in available2]}")

    # Test 3: Get workflow chain
    print("\n🔗 Workflow Chains:")
    chain = registry.get_action_chain("figma_to_production")
    print(f"   figma_to_production: {chain}")

    # Test 4: Search actions
    print("\n🔍 Search Results:")
    results = registry.search_actions("deploy")
    print(f"   'deploy' search: {[a.name for a in results]}")


if __name__ == "__main__":
    test_action_registry()
