"""
Universal Command Router for GodComet
Routes commands to appropriate tools based on pattern matching and context
"""

import re
import logging
from typing import Dict, Optional, Callable, List, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class CommandType(Enum):
    """Types of commands that can be routed"""
    FIGMA = "figma"
    YOUTUBE = "youtube"
    BROWSER_NAVIGATE = "browser_navigate"
    BROWSER_SCREENSHOT = "browser_screenshot"
    BROWSER_SCROLL = "browser_scroll"
    BROWSER_CLICK = "browser_click"
    BROWSER_TYPE = "browser_type"
    BROWSER_BACK = "browser_back"
    BROWSER_REFRESH = "browser_refresh"
    DEPLOY_VERCEL = "deploy_vercel"
    DEPLOY_GITHUB = "deploy_github"
    FILE_OPERATION = "file_operation"
    NATURAL_LANGUAGE = "natural_language"


@dataclass
class CommandMatch:
    """Result of command pattern matching"""
    command_type: CommandType
    confidence: float  # 0.0 to 1.0
    extracted_params: Dict
    original_command: str


@dataclass
class CommandPattern:
    """A pattern for matching commands"""
    command_type: CommandType
    patterns: List[str]  # Regex patterns
    extract_params: Callable[[re.Match, str], Dict]
    priority: int = 0  # Higher priority matched first


class UniversalCommandRouter:
    """
    Routes commands to appropriate handlers based on pattern matching

    Supports:
    - Figma URLs: figma.com/file/... or figma.com/design/...
    - YouTube: play [song], youtube [query]
    - Browser: open [site], go to [url], navigate to [url]
    - Screenshots: screenshot, take screenshot, capture screen
    - Scroll: scroll up/down/left/right
    - Click: click [element], click on [element]
    - Type: type [text] in [field], enter [text] in [field]
    - Navigation: go back, refresh, reload
    - Deploy: deploy to vercel, push to github
    """

    def __init__(self):
        self.patterns: List[CommandPattern] = []
        self._register_default_patterns()

    def _register_default_patterns(self):
        """Register default command patterns"""

        # Figma URL detection (highest priority)
        self.register_pattern(CommandPattern(
            command_type=CommandType.FIGMA,
            patterns=[
                r'(?:https?://)?(?:www\.)?figma\.com/(?:file|design|proto)/([a-zA-Z0-9]+)(?:/[^?\s]*)?(?:\?[^\s]*)?',
                r'figma\.com/(?:file|design)/([a-zA-Z0-9]+)',
            ],
            extract_params=lambda m, cmd: {
                "figma_url": m.group(0) if not m.group(0).startswith('http') else m.group(0),
                "file_id": m.group(1) if m.groups() else None
            },
            priority=100
        ))

        # YouTube playback
        self.register_pattern(CommandPattern(
            command_type=CommandType.YOUTUBE,
            patterns=[
                r'(?:play|youtube|watch)\s+(?:video\s+)?["\']?(.+?)["\']?\s*(?:on\s+youtube)?$',
                r'(?:play|listen\s+to)\s+(.+?)\s+(?:on\s+youtube|music)',
                r'youtube\s+(.+)',
            ],
            extract_params=lambda m, cmd: {"query": m.group(1).strip()},
            priority=90
        ))

        # Browser navigation
        self.register_pattern(CommandPattern(
            command_type=CommandType.BROWSER_NAVIGATE,
            patterns=[
                r'(?:open|go\s+to|navigate\s+to|visit)\s+(?:the\s+)?(?:website\s+)?["\']?([^\s"\']+(?:\.[^\s"\']+)+)["\']?',
                r'(?:open|go\s+to)\s+["\']?([a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}(?:/[^\s]*)?)["\']?',
                r'(?:https?://[^\s]+)',
            ],
            extract_params=lambda m, cmd: {
                "url": m.group(1) if m.groups() else m.group(0),
                "add_https": not m.group(0).startswith('http')
            },
            priority=80
        ))

        # Screenshot
        self.register_pattern(CommandPattern(
            command_type=CommandType.BROWSER_SCREENSHOT,
            patterns=[
                r'(?:take\s+)?(?:a\s+)?screenshot(?:\s+of\s+(.+))?',
                r'capture\s+(?:the\s+)?(?:screen|page|window)',
                r'snap(?:\s+the\s+screen)?',
            ],
            extract_params=lambda m, cmd: {
                "target": m.group(1) if m.groups() and m.group(1) else "full_page"
            },
            priority=70
        ))

        # Scroll
        self.register_pattern(CommandPattern(
            command_type=CommandType.BROWSER_SCROLL,
            patterns=[
                r'scroll\s+(up|down|left|right|top|bottom)(?:\s+(\d+)\s*(?:px|pixels)?)?',
                r'(?:go\s+to\s+)?(?:the\s+)?(top|bottom)\s+(?:of\s+)?(?:the\s+)?page',
            ],
            extract_params=lambda m, cmd: {
                "direction": m.group(1).lower(),
                "amount": int(m.group(2)) if m.groups() and len(m.groups()) > 1 and m.group(2) else 500
            },
            priority=60
        ))

        # Click
        self.register_pattern(CommandPattern(
            command_type=CommandType.BROWSER_CLICK,
            patterns=[
                r'click\s+(?:on\s+)?(?:the\s+)?["\']?(.+?)["\']?(?:\s+button)?$',
                r'press\s+(?:the\s+)?["\']?(.+?)["\']?(?:\s+button)?$',
                r'tap\s+(?:on\s+)?["\']?(.+?)["\']?$',
            ],
            extract_params=lambda m, cmd: {"element": m.group(1).strip()},
            priority=50
        ))

        # Type/Fill
        self.register_pattern(CommandPattern(
            command_type=CommandType.BROWSER_TYPE,
            patterns=[
                r'(?:type|enter|input|fill)\s+["\']?(.+?)["\']?\s+(?:in|into)\s+(?:the\s+)?["\']?(.+?)["\']?$',
                r'(?:type|enter)\s+["\']?(.+?)["\']?$',
            ],
            extract_params=lambda m, cmd: {
                "text": m.group(1).strip(),
                "field": m.group(2).strip() if m.groups() and len(m.groups()) > 1 and m.group(2) else "active"
            },
            priority=50
        ))

        # Browser back
        self.register_pattern(CommandPattern(
            command_type=CommandType.BROWSER_BACK,
            patterns=[
                r'(?:go\s+)?back(?:\s+(?:one\s+)?page)?',
                r'previous\s+page',
            ],
            extract_params=lambda m, cmd: {},
            priority=40
        ))

        # Browser refresh
        self.register_pattern(CommandPattern(
            command_type=CommandType.BROWSER_REFRESH,
            patterns=[
                r'(?:refresh|reload)(?:\s+(?:the\s+)?page)?',
                r'f5',
            ],
            extract_params=lambda m, cmd: {},
            priority=40
        ))

        # Deploy to Vercel
        self.register_pattern(CommandPattern(
            command_type=CommandType.DEPLOY_VERCEL,
            patterns=[
                r'deploy(?:\s+(?:to|on))?\s+vercel',
                r'vercel\s+deploy',
                r'push\s+to\s+vercel',
            ],
            extract_params=lambda m, cmd: {},
            priority=70
        ))

        # Deploy to GitHub
        self.register_pattern(CommandPattern(
            command_type=CommandType.DEPLOY_GITHUB,
            patterns=[
                r'(?:push|deploy|upload)(?:\s+(?:to|on))?\s+github',
                r'create\s+(?:a\s+)?github\s+repo(?:sitory)?',
                r'github\s+push',
            ],
            extract_params=lambda m, cmd: {},
            priority=70
        ))

    def register_pattern(self, pattern: CommandPattern):
        """Register a new command pattern"""
        self.patterns.append(pattern)
        # Sort by priority (highest first)
        self.patterns.sort(key=lambda p: p.priority, reverse=True)

    def match(self, command: str) -> Optional[CommandMatch]:
        """
        Match a command against registered patterns

        Args:
            command: The user's command string

        Returns:
            CommandMatch if a pattern matches, None otherwise
        """
        command_lower = command.lower().strip()

        for pattern in self.patterns:
            for regex in pattern.patterns:
                try:
                    match = re.search(regex, command_lower, re.IGNORECASE)
                    if match:
                        params = pattern.extract_params(match, command)

                        # Calculate confidence based on match coverage
                        match_length = len(match.group(0))
                        coverage = match_length / len(command)
                        confidence = min(1.0, coverage + 0.2)  # Bonus for matching

                        logger.info(f"Matched command '{command}' as {pattern.command_type.value} "
                                   f"(confidence: {confidence:.2f})")

                        return CommandMatch(
                            command_type=pattern.command_type,
                            confidence=confidence,
                            extracted_params=params,
                            original_command=command
                        )
                except Exception as e:
                    logger.error(f"Error matching pattern {regex}: {e}")
                    continue

        # No match - treat as natural language
        logger.info(f"No pattern match for '{command}', treating as natural language")
        return CommandMatch(
            command_type=CommandType.NATURAL_LANGUAGE,
            confidence=0.5,
            extracted_params={"query": command},
            original_command=command
        )

    def get_command_type(self, command: str) -> CommandType:
        """Get the command type for a command string"""
        match = self.match(command)
        return match.command_type if match else CommandType.NATURAL_LANGUAGE

    def is_figma_url(self, command: str) -> bool:
        """Check if command contains a Figma URL"""
        match = self.match(command)
        return match is not None and match.command_type == CommandType.FIGMA

    def extract_figma_url(self, command: str) -> Optional[str]:
        """Extract Figma URL from command"""
        match = self.match(command)
        if match and match.command_type == CommandType.FIGMA:
            url = match.extracted_params.get("figma_url", "")
            if not url.startswith("http"):
                url = f"https://{url}"
            return url
        return None


# Global instance
command_router = UniversalCommandRouter()


def get_command_router() -> UniversalCommandRouter:
    """Get the global command router instance"""
    return command_router


# Convenience functions
def route_command(command: str) -> CommandMatch:
    """Route a command using the global router"""
    return command_router.match(command)


def is_figma_command(command: str) -> bool:
    """Check if a command is a Figma command"""
    return command_router.is_figma_url(command)


def get_figma_url(command: str) -> Optional[str]:
    """Extract Figma URL from a command"""
    return command_router.extract_figma_url(command)


# Test function
if __name__ == "__main__":
    router = UniversalCommandRouter()

    test_commands = [
        "https://figma.com/file/abc123/MyDesign",
        "figma.com/design/xyz789/Homepage?node-id=123",
        "play bohemian rhapsody on youtube",
        "open github.com",
        "go to google.com",
        "take a screenshot",
        "scroll down",
        "click the login button",
        "type hello in search box",
        "go back",
        "refresh the page",
        "deploy to vercel",
        "push to github",
        "what's the weather today",  # Natural language
    ]

    print("Testing Universal Command Router")
    print("=" * 60)

    for cmd in test_commands:
        match = router.match(cmd)
        print(f"\nCommand: {cmd}")
        print(f"  Type: {match.command_type.value}")
        print(f"  Confidence: {match.confidence:.2f}")
        print(f"  Params: {match.extracted_params}")
