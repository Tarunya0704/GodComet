"""
Interactive Browser Testing - Beyond Screenshots
Uses Playwright to interact with websites (click, type, verify)
"""

import asyncio
from typing import Dict, List, Optional
from pathlib import Path
from playwright.async_api import async_playwright, Browser, Page, ElementHandle


class InteractiveBrowser:
    """
    Extended Playwright automation for interactive testing
    Goes beyond screenshots to verify actual functionality
    """

    def __init__(self):
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None

    async def __aenter__(self):
        """Context manager entry"""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=False)  # Visible for debugging
        self.page = await self.browser.new_page()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        if self.browser:
            await self.browser.close()
        if hasattr(self, 'playwright'):
            await self.playwright.stop()

    async def test_user_flow(
        self,
        url: str,
        flow_steps: List[Dict]
    ) -> Dict:
        """
        Test a complete user flow

        Args:
            url: Starting URL
            flow_steps: List of steps like:
                [
                    {"action": "navigate", "url": "https://..."},
                    {"action": "click", "selector": "button.login"},
                    {"action": "type", "selector": "input[name=email]", "text": "test@example.com"},
                    {"action": "verify", "selector": "div.success", "contains": "Welcome"}
                ]

        Returns:
            {
                "success": True/False,
                "steps_completed": 4,
                "total_steps": 4,
                "screenshots": [...],
                "errors": [...]
            }
        """
        print(f"🧪 Testing user flow: {len(flow_steps)} steps")

        results = {
            "success": True,
            "steps_completed": 0,
            "total_steps": len(flow_steps),
            "screenshots": [],
            "errors": []
        }

        try:
            # Navigate to initial URL
            await self.page.goto(url, wait_until="networkidle")
            print(f"   ✅ Navigated to {url}")

            # Execute each step
            for i, step in enumerate(flow_steps, 1):
                action = step.get("action")
                print(f"   Step {i}/{len(flow_steps)}: {action}")

                try:
                    if action == "navigate":
                        await self._action_navigate(step)
                    elif action == "click":
                        await self._action_click(step)
                    elif action == "type":
                        await self._action_type(step)
                    elif action == "verify":
                        await self._action_verify(step)
                    elif action == "wait":
                        await self._action_wait(step)
                    elif action == "screenshot":
                        screenshot_path = await self._action_screenshot(step)
                        results["screenshots"].append(screenshot_path)
                    else:
                        raise ValueError(f"Unknown action: {action}")

                    results["steps_completed"] += 1
                    print(f"   ✅ Step {i} completed")

                except Exception as e:
                    error_msg = f"Step {i} failed: {str(e)}"
                    print(f"   ❌ {error_msg}")
                    results["errors"].append(error_msg)
                    results["success"] = False

                    # Take error screenshot
                    error_screenshot = await self.page.screenshot()
                    error_path = f"error_step_{i}.png"
                    with open(error_path, "wb") as f:
                        f.write(error_screenshot)
                    results["screenshots"].append(error_path)

                    break  # Stop on first error

            print(f"\n   {'✅ Flow completed' if results['success'] else '❌ Flow failed'}")
            return results

        except Exception as e:
            results["success"] = False
            results["errors"].append(f"Flow execution error: {str(e)}")
            return results

    async def _action_navigate(self, step: Dict):
        """Navigate to URL"""
        url = step.get("url")
        await self.page.goto(url, wait_until="networkidle")

    async def _action_click(self, step: Dict):
        """Click an element"""
        selector = step.get("selector")
        await self.page.click(selector, timeout=5000)
        await self.page.wait_for_load_state("networkidle")

    async def _action_type(self, step: Dict):
        """Type text into an input"""
        selector = step.get("selector")
        text = step.get("text", "")
        await self.page.fill(selector, text, timeout=5000)

    async def _action_verify(self, step: Dict):
        """Verify element exists or contains text"""
        selector = step.get("selector")
        contains = step.get("contains")

        # Wait for element
        element = await self.page.wait_for_selector(selector, timeout=5000)

        if contains:
            text = await element.text_content()
            if contains not in text:
                raise AssertionError(f"Element '{selector}' does not contain '{contains}'. Found: '{text}'")

    async def _action_wait(self, step: Dict):
        """Wait for a duration or condition"""
        duration = step.get("duration", 1000)  # milliseconds
        await self.page.wait_for_timeout(duration)

    async def _action_screenshot(self, step: Dict) -> str:
        """Take a screenshot"""
        output_path = step.get("output", "screenshot.png")
        await self.page.screenshot(path=output_path)
        return output_path

    async def verify_deployment(
        self,
        url: str,
        expected_elements: List[str],
        figma_screenshot: Optional[str] = None
    ) -> Dict:
        """
        Verify a deployment works correctly

        Args:
            url: URL to test
            expected_elements: List of CSS selectors that must exist
            figma_screenshot: Optional Figma screenshot for visual comparison

        Returns:
            {
                "url_accessible": True/False,
                "all_elements_present": True/False,
                "missing_elements": [...],
                "console_errors": [...],
                "visual_match": 0.95 (if figma_screenshot provided)
            }
        """
        print(f"🧪 Verifying deployment: {url}")

        result = {
            "url_accessible": False,
            "all_elements_present": False,
            "missing_elements": [],
            "console_errors": [],
            "visual_match": None
        }

        try:
            # Listen for console errors
            self.page.on("console", lambda msg:
                result["console_errors"].append(msg.text) if msg.type == "error" else None
            )

            # Navigate
            response = await self.page.goto(url, wait_until="networkidle", timeout=30000)
            result["url_accessible"] = response.status < 400
            print(f"   ✅ URL accessible (status {response.status})")

            # Check for expected elements
            for selector in expected_elements:
                try:
                    await self.page.wait_for_selector(selector, timeout=2000)
                except:
                    result["missing_elements"].append(selector)

            result["all_elements_present"] = len(result["missing_elements"]) == 0

            if result["all_elements_present"]:
                print(f"   ✅ All {len(expected_elements)} elements present")
            else:
                print(f"   ⚠️  Missing elements: {result['missing_elements']}")

            # Visual comparison (if Figma screenshot provided)
            if figma_screenshot:
                from .visual_auditor import VisualAuditor

                # Take screenshot of deployment
                deployed_screenshot = "deployed_screenshot.png"
                await self.page.screenshot(path=deployed_screenshot)

                # Compare
                auditor = VisualAuditor()
                audit_result = auditor.audit(figma_screenshot, deployed_screenshot)
                result["visual_match"] = audit_result["score"]

                print(f"   📊 Visual match: {result['visual_match']:.1%}")

            return result

        except Exception as e:
            print(f"   ❌ Verification failed: {e}")
            result["error"] = str(e)
            return result

    async def test_responsive_design(
        self,
        url: str,
        viewports: List[Dict] = None
    ) -> Dict:
        """
        Test design at multiple viewport sizes

        Args:
            viewports: List of {width, height} dicts
                       Default: mobile, tablet, desktop

        Returns:
            {
                "mobile": {"screenshot": "...", "elements_visible": True},
                "tablet": {...},
                "desktop": {...}
            }
        """
        if not viewports:
            viewports = [
                {"name": "mobile", "width": 375, "height": 667},
                {"name": "tablet", "width": 768, "height": 1024},
                {"name": "desktop", "width": 1440, "height": 900}
            ]

        print(f"🧪 Testing responsive design at {len(viewports)} viewport sizes")

        results = {}

        for viewport in viewports:
            name = viewport["name"]
            print(f"   Testing {name} ({viewport['width']}x{viewport['height']})...")

            await self.page.set_viewport_size({
                "width": viewport["width"],
                "height": viewport["height"]
            })

            await self.page.goto(url, wait_until="networkidle")
            await self.page.wait_for_timeout(1000)

            screenshot_path = f"{name}_screenshot.png"
            await self.page.screenshot(path=screenshot_path)

            # Check if content is visible (basic check)
            body_visible = await self.page.is_visible("body")

            results[name] = {
                "screenshot": screenshot_path,
                "elements_visible": body_visible,
                "viewport": viewport
            }

            print(f"   ✅ {name} tested")

        return results

    async def extract_form_structure(self, url: str) -> Dict:
        """
        Extract form structure for automated testing

        Returns:
            {
                "forms": [
                    {
                        "selector": "form#login",
                        "inputs": [
                            {"type": "email", "name": "email", "required": True},
                            {"type": "password", "name": "password", "required": True}
                        ],
                        "submit_button": "button[type=submit]"
                    }
                ]
            }
        """
        await self.page.goto(url, wait_until="networkidle")

        forms_data = await self.page.evaluate("""
            () => {
                const forms = Array.from(document.querySelectorAll('form'));
                return forms.map(form => ({
                    selector: form.id ? `form#${form.id}` : `form.${form.className}`,
                    inputs: Array.from(form.querySelectorAll('input, textarea, select')).map(input => ({
                        type: input.type,
                        name: input.name,
                        id: input.id,
                        required: input.required,
                        placeholder: input.placeholder
                    })),
                    submitButton: form.querySelector('button[type=submit]') ? 'button[type=submit]' : 'input[type=submit]'
                }));
            }
        """)

        return {"forms": forms_data}


# Standalone test
async def test_interactive_browser():
    """Test interactive browser"""
    print("🧪 Testing Interactive Browser\n")

    async with InteractiveBrowser() as browser:
        # Test 1: Simple user flow
        print("Test 1: User Flow Simulation")
        flow = [
            {"action": "navigate", "url": "https://example.com"},
            {"action": "wait", "duration": 1000},
            {"action": "screenshot", "output": "example.png"},
            {"action": "verify", "selector": "h1", "contains": "Example"}
        ]

        result = await browser.test_user_flow("https://example.com", flow)
        print(f"Result: {result}\n")

        # Test 2: Responsive design
        print("Test 2: Responsive Design Test")
        responsive_result = await browser.test_responsive_design("https://example.com")
        print(f"Result: {responsive_result.keys()}\n")

        # Test 3: Form extraction
        print("Test 3: Form Structure Extraction")
        form_structure = await browser.extract_form_structure("https://example.com")
        print(f"Result: {form_structure}")


if __name__ == "__main__":
    asyncio.run(test_interactive_browser())
