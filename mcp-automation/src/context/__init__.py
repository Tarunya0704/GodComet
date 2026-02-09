"""
Context Detection System - The "Brain" of the Agentic OS
Aggregates context from VS Code, Chrome, Desktop, and Clipboard
"""

from .context_aggregator import ContextAggregator
from .desktop_vision import DesktopVisionDetector
from .action_registry import ActionRegistry

__all__ = [
    "ContextAggregator",
    "DesktopVisionDetector",
    "ActionRegistry",
]
