"""MCP Tools package"""
from .browser_tool import BrowserTool
from .aws_tool import AWSTool
from .system_tool import SystemTool

# Import with correct name
try:
    from .jira_tool import UniversalJiraAutomation
except ImportError:
    UniversalJiraAutomation = None

# Import document parser
try:
    from .document_parser import DocumentParser, DocumentToJiraAutomation
except ImportError:
    DocumentParser = None
    DocumentToJiraAutomation = None

# NEW: Import visual browser automation
try:
    from .jira_browser_automation import JiraBrowserAutomation
except ImportError:
    JiraBrowserAutomation = None

__all__ = [
    'BrowserTool', 
    'AWSTool', 
    'SystemTool', 
    'UniversalJiraAutomation',
    'DocumentParser',
    'DocumentToJiraAutomation',
    'JiraBrowserAutomation'  # NEW
]