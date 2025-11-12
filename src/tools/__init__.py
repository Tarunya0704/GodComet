# """MCP Tools package"""
# from .browser_tool import BrowserTool
# from .aws_tool import AWSTool
# from .system_tool import SystemTool

# # Import with correct name
# try:
#     from .jira_tool import UniversalJiraAutomation
# except ImportError:
#     UniversalJiraAutomation = None

# # Import document parser
# try:
#     from .document_parser import DocumentParser, DocumentToJiraAutomation
# except ImportError:
#     DocumentParser = None
#     DocumentToJiraAutomation = None

# # NEW: Import visual browser automation
# try:
#     from .jira_browser_automation import JiraBrowserAutomation
# except ImportError:
#     JiraBrowserAutomation = None

# __all__ = [
#     'BrowserTool', 
#     'AWSTool', 
#     'SystemTool', 
#     'UniversalJiraAutomation',
#     'DocumentParser',
#     'DocumentToJiraAutomation',
#     'JiraBrowserAutomation'  # NEW
# ]

"""Tools package - Updated with GitHub and Vercel"""

from .browser_tool import BrowserTool
from .aws_tool import AWSTool
from .system_tool import SystemTool

# Optional imports with error handling
try:
    from .jira_tool import UniversalJiraAutomation
except ImportError:
    UniversalJiraAutomation = None

try:
    from .jira_browser_automation import JiraBrowserAutomation
except ImportError:
    JiraBrowserAutomation = None

try:
    from .document_parser import DocumentParser
except ImportError:
    DocumentParser = None

try:
    from .github_tool import GitHubTool
except ImportError:
    GitHubTool = None

try:
    from .vercel_tool import VercelTool
except ImportError:
    VercelTool = None
try:
    from .figma_to_website_tool import FigmaToWebsiteTool
except ImportError:
    FigmaToWebsiteTool = None

try:
    from .document_generator_tool import DocumentGeneratorTool
except ImportError:
    DocumentGeneratorTool = None

__all__ = [
    'BrowserTool',
    'AWSTool',
    'SystemTool',
    'UniversalJiraAutomation',
    'JiraBrowserAutomation',
    'DocumentParser',
    'GitHubTool',
    'VercelTool',
    'FigmaToWebsiteTool',
    'DocumentGeneratorTool',
]