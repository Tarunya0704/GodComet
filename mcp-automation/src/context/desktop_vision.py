"""
Desktop Vision Detector - Uses Vision AI to understand desktop state
Takes screenshots and detects which apps/content are visible
"""

import os
import base64
from typing import Dict, List, Optional
from pathlib import Path
from PIL import ImageGrab
import json

# Vision API clients
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    from anthropic import Anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False


class DesktopVisionDetector:
    """
    Takes desktop screenshots and uses Vision AI to detect:
    - Which applications are visible
    - What the user is working on
    - Visual context (Figma design, code editor, browser, etc.)
    """

    def __init__(
        self,
        use_openai: bool = True,
        use_anthropic: bool = False,
        openai_model: str = "gpt-4o-mini",
        anthropic_model: str = "claude-3-5-sonnet-20241022"
    ):
        self.use_openai = use_openai
        self.use_anthropic = use_anthropic

        # Initialize API clients
        self.openai_client = None
        self.anthropic_client = None

        if use_openai and OPENAI_AVAILABLE:
            api_key = os.getenv("OPENAI_API_KEY")
            if api_key:
                self.openai_client = OpenAI(api_key=api_key)
                self.openai_model = openai_model

        if use_anthropic and ANTHROPIC_AVAILABLE:
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if api_key:
                self.anthropic_client = Anthropic(api_key=api_key)
                self.anthropic_model = anthropic_model

    async def analyze_desktop(self, screenshot_path: Optional[str] = None) -> Dict:
        """
        Analyze desktop screenshot to detect visible apps and context

        Returns:
            {
                "visible_apps": ["VS Code", "Chrome", "Figma"],
                "primary_focus": "VS Code",
                "detected_content": {
                    "vscode": {"file": "Auth.tsx", "language": "TypeScript"},
                    "chrome": {"url": "figma.com/file/abc123", "is_figma": True},
                    "figma": {"design_name": "Login Flow"}
                },
                "user_intent": "Implementing Figma design in code",
                "recommended_actions": ["generate_code_from_figma"]
            }
        """
        print("👁️  Analyzing desktop with Vision AI...")

        # Take screenshot if not provided
        if not screenshot_path:
            screenshot_path = await self._take_screenshot()

        # Analyze with Vision AI
        if self.openai_client:
            return await self._analyze_with_openai(screenshot_path)
        elif self.anthropic_client:
            return await self._analyze_with_anthropic(screenshot_path)
        else:
            return {
                "error": "No vision models available",
                "screenshot_path": screenshot_path
            }

    async def _take_screenshot(self) -> str:
        """Take a screenshot of the entire desktop"""
        try:
            # Create screenshots directory
            screenshots_dir = Path.home() / ".godcomet" / "screenshots"
            screenshots_dir.mkdir(parents=True, exist_ok=True)

            # Take screenshot
            screenshot = ImageGrab.grab()

            # Save
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_path = screenshots_dir / f"desktop_{timestamp}.png"
            screenshot.save(screenshot_path)

            print(f"   📸 Screenshot saved: {screenshot_path}")
            return str(screenshot_path)

        except Exception as e:
            print(f"   ⚠️  Screenshot failed: {e}")
            raise

    async def _analyze_with_openai(self, screenshot_path: str) -> Dict:
        """Analyze screenshot with OpenAI GPT-4o"""
        try:
            # Encode image
            with open(screenshot_path, "rb") as f:
                image_b64 = base64.b64encode(f.read()).decode("utf-8")

            prompt = self._build_vision_prompt()

            response = self.openai_client.chat.completions.create(
                model=self.openai_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_b64}",
                                    "detail": "high"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=1000,
                temperature=0.1
            )

            content = response.choices[0].message.content
            return self._parse_vision_response(content, screenshot_path)

        except Exception as e:
            print(f"   ⚠️  OpenAI vision failed: {e}")
            return {"error": str(e), "screenshot_path": screenshot_path}

    async def _analyze_with_anthropic(self, screenshot_path: str) -> Dict:
        """Analyze screenshot with Anthropic Claude"""
        try:
            # Encode image
            with open(screenshot_path, "rb") as f:
                image_b64 = base64.b64encode(f.read()).decode("utf-8")

            prompt = self._build_vision_prompt()

            response = self.anthropic_client.messages.create(
                model=self.anthropic_model,
                max_tokens=1000,
                temperature=0.1,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": image_b64
                                }
                            }
                        ]
                    }
                ]
            )

            content = response.content[0].text
            return self._parse_vision_response(content, screenshot_path)

        except Exception as e:
            print(f"   ⚠️  Claude vision failed: {e}")
            return {"error": str(e), "screenshot_path": screenshot_path}

    def _build_vision_prompt(self) -> str:
        """Build prompt for desktop vision analysis"""
        return """Analyze this desktop screenshot and identify:

1. **Visible Applications**: What apps are open? (VS Code, Chrome, Figma, Terminal, etc.)
2. **Primary Focus**: Which app is the user actively working in?
3. **Detected Content**:
   - If VS Code is visible: What file/language is being edited?
   - If Chrome is visible: What website (especially if it's Figma, GitHub, etc.)?
   - If Figma is visible: What design is being worked on?
4. **User Intent**: What is the user trying to accomplish?
5. **Recommended Actions**: What actions would help the user? (e.g., "generate_code_from_figma", "deploy_to_vercel")

Return your analysis as JSON:
```json
{
  "visible_apps": ["VS Code", "Chrome"],
  "primary_focus": "VS Code",
  "detected_content": {
    "vscode": {
      "file": "Auth.tsx",
      "language": "TypeScript",
      "visible_code": "Brief summary of visible code"
    },
    "chrome": {
      "url": "figma.com/file/abc123",
      "title": "Login Flow Design",
      "is_figma": true
    }
  },
  "user_intent": "Implementing Figma design in code",
  "recommended_actions": ["generate_code_from_figma", "verify_design_implementation"]
}
```

Be specific and accurate. Only mention apps you can clearly see."""

    def _parse_vision_response(self, content: str, screenshot_path: str) -> Dict:
        """Parse Vision AI response"""
        try:
            # Extract JSON from response
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0].strip()
            else:
                json_str = content.strip()

            data = json.loads(json_str)
            data["screenshot_path"] = screenshot_path

            print(f"   ✅ Detected apps: {', '.join(data.get('visible_apps', []))}")
            print(f"   🎯 Intent: {data.get('user_intent', 'unknown')}")

            return data

        except json.JSONDecodeError as e:
            print(f"   ⚠️  Failed to parse vision response: {e}")
            return {
                "error": "Parse error",
                "raw_response": content[:200],
                "screenshot_path": screenshot_path
            }

    def enhance_context_with_vision(self, base_context: Dict, vision_result: Dict) -> Dict:
        """
        Enhance existing context with vision analysis

        Combines traditional context (WebSocket data) with vision insights
        """
        enhanced = base_context.copy()

        # Add vision data
        enhanced["vision"] = vision_result

        # Cross-validate: If vision says "VS Code" but WebSocket says inactive, trust vision
        vscode_sources = enhanced.get("sources", {}).get("vscode", {})
        vision_apps = vision_result.get("visible_apps", [])

        if "VS Code" in vision_apps and not vscode_sources.get("active"):
            enhanced["sources"]["vscode"]["active"] = True
            enhanced["sources"]["vscode"]["detected_by"] = "vision"

        # Enrich intent
        vision_intent = vision_result.get("user_intent", "")
        if vision_intent:
            enhanced["intent"] = vision_intent

        # Merge recommended actions
        base_actions = enhanced.get("recommended_actions", [])
        vision_actions = vision_result.get("recommended_actions", [])
        enhanced["recommended_actions"] = list(set(base_actions + vision_actions))

        return enhanced


# Standalone test
async def test_desktop_vision():
    """Test desktop vision detection"""
    print("🧪 Testing Desktop Vision Detector\n")

    detector = DesktopVisionDetector()

    # Analyze current desktop
    result = await detector.analyze_desktop()

    print("\n📊 Vision Analysis:")
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_desktop_vision())
