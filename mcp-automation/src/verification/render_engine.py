"""
Render Engine - Uses Playwright to render generated code and capture screenshots
Handles viewport matching, font loading, and DOM extraction
"""

import os
import asyncio
import subprocess
import time
from typing import Dict, Optional, Tuple
from pathlib import Path
from playwright.async_api import async_playwright, Browser, Page


class RenderEngine:
    """
    Renders generated React/Next.js code using Playwright
    Captures screenshots and DOM trees for verification
    """

    def __init__(
        self,
        default_viewport_width: int = 1440,
        default_viewport_height: int = 900,
        wait_for_fonts: int = 2000,  # ms to wait for fonts to load
        disable_animations: bool = True
    ):
        """
        Initialize Render Engine

        Args:
            default_viewport_width: Default viewport width
            default_viewport_height: Default viewport height
            wait_for_fonts: Milliseconds to wait for fonts to load
            disable_animations: Disable CSS animations for consistent screenshots
        """
        self.default_viewport = {
            "width": default_viewport_width,
            "height": default_viewport_height
        }
        self.wait_for_fonts = wait_for_fonts
        self.disable_animations = disable_animations
        self.dev_servers = {}  # Track running dev servers

    async def render(
        self,
        project_path: str,
        viewport_width: Optional[int] = None,
        viewport_height: Optional[int] = None,
        output_path: Optional[str] = None,
        full_page: bool = True
    ) -> Dict:
        """
        Main render function - starts dev server, captures screenshot

        Returns:
            {
                "screenshot_path": "/path/to/screenshot.png",
                "dom_tree": "<html>...</html>",
                "url": "http://localhost:3000",
                "viewport": {"width": 1440, "height": 900},
                "metadata": {...}
            }
        """
        print(f"🎬 Starting render pipeline for: {project_path}")

        # Use default viewport if not specified
        viewport = {
            "width": viewport_width or self.default_viewport["width"],
            "height": viewport_height or self.default_viewport["height"]
        }

        # Step 1: Start development server
        server_url, server_process = await self._start_dev_server(project_path)
        print(f"   🌐 Dev server running: {server_url}")

        try:
            # Step 2: Launch browser and navigate
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        '--disable-web-security',  # For local dev
                        '--disable-features=IsolateOrigins,site-per-process'
                    ]
                )

                page = await browser.new_page(viewport=viewport)

                # Disable animations if requested
                if self.disable_animations:
                    await self._disable_animations(page)

                # Navigate to the dev server
                print(f"   🔗 Navigating to {server_url}...")
                await page.goto(server_url, wait_until="networkidle", timeout=60000)

                # Wait for fonts and images
                await page.wait_for_timeout(self.wait_for_fonts)
                print(f"   ⏳ Waited {self.wait_for_fonts}ms for assets to load")

                # Step 3: Capture screenshot
                if not output_path:
                    output_dir = Path(project_path) / "screenshots"
                    output_dir.mkdir(exist_ok=True)
                    timestamp = int(time.time())
                    output_path = str(output_dir / f"render_{timestamp}.png")

                screenshot_bytes = await page.screenshot(
                    path=output_path,
                    full_page=full_page,
                    type="png"
                )
                print(f"   📸 Screenshot saved: {output_path}")

                # Step 4: Extract DOM tree
                dom_tree = await page.content()

                # Step 5: Get accessibility tree (useful for semantic analysis)
                accessibility_tree = await self._get_accessibility_tree(page)

                await browser.close()

                result = {
                    "screenshot_path": output_path,
                    "dom_tree": dom_tree,
                    "accessibility_tree": accessibility_tree,
                    "url": server_url,
                    "viewport": viewport,
                    "metadata": {
                        "project_path": project_path,
                        "full_page": full_page,
                        "animations_disabled": self.disable_animations
                    }
                }

                print(f"   ✅ Render complete!")
                return result

        finally:
            # Step 6: Cleanup - stop dev server
            await self._stop_dev_server(server_process)

    async def _start_dev_server(self, project_path: str) -> Tuple[str, subprocess.Popen]:
        """
        Start Next.js/React dev server and wait for it to be ready
        """
        project_dir = Path(project_path)

        # Check if package.json exists
        package_json = project_dir / "package.json"
        if not package_json.exists():
            raise FileNotFoundError(f"package.json not found in {project_path}")

        # Detect framework and port
        port = self._find_available_port(3000)

        # Check if dependencies are installed
        node_modules = project_dir / "node_modules"
        if not node_modules.exists():
            print(f"   📦 Installing dependencies...")
            install_process = subprocess.run(
                ["npm", "install"],
                cwd=str(project_dir),
                capture_output=True,
                text=True,
                shell=True
            )
            if install_process.returncode != 0:
                print(f"   ⚠️  npm install warnings: {install_process.stderr[:200]}")

        # Start dev server (Next.js or Vite)
        # Try Next.js first
        print(f"   🚀 Starting dev server on port {port}...")

        # Use "npm run dev" which works for both Next.js and Vite
        env = os.environ.copy()
        env["PORT"] = str(port)

        server_process = subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=str(project_dir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=True
        )

        # Wait for server to be ready (max 30 seconds)
        server_url = f"http://localhost:{port}"
        max_wait = 30
        waited = 0

        while waited < max_wait:
            try:
                # Try to connect
                import requests
                response = requests.get(server_url, timeout=1)
                if response.status_code == 200:
                    print(f"   ✅ Server ready after {waited}s")
                    break
            except:
                pass

            await asyncio.sleep(1)
            waited += 1

            # Check if process died
            if server_process.poll() is not None:
                stderr = server_process.stderr.read()
                raise RuntimeError(f"Dev server failed to start: {stderr}")

        if waited >= max_wait:
            server_process.kill()
            raise TimeoutError(f"Dev server did not start within {max_wait}s")

        return server_url, server_process

    async def _stop_dev_server(self, server_process: subprocess.Popen):
        """Stop the development server"""
        if server_process:
            print(f"   🛑 Stopping dev server...")
            server_process.terminate()
            try:
                server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server_process.kill()

    def _find_available_port(self, start_port: int = 3000) -> int:
        """Find an available port starting from start_port"""
        import socket
        port = start_port
        while port < start_port + 100:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(('localhost', port)) != 0:
                    return port
                port += 1
        raise RuntimeError(f"No available ports found between {start_port} and {start_port + 100}")

    async def _disable_animations(self, page: Page):
        """Inject CSS to disable all animations"""
        await page.add_style_tag(content="""
            *, *::before, *::after {
                animation-duration: 0s !important;
                animation-delay: 0s !important;
                transition-duration: 0s !important;
                transition-delay: 0s !important;
            }
        """)

    async def _get_accessibility_tree(self, page: Page) -> Optional[Dict]:
        """Get accessibility tree snapshot"""
        try:
            snapshot = await page.accessibility.snapshot()
            return snapshot
        except Exception as e:
            print(f"   ⚠️  Could not get accessibility tree: {e}")
            return None

    async def render_static_html(
        self,
        html_path: str,
        viewport_width: Optional[int] = None,
        viewport_height: Optional[int] = None,
        output_path: Optional[str] = None
    ) -> Dict:
        """
        Render a static HTML file (no dev server needed)
        Useful for quick previews
        """
        print(f"🎬 Rendering static HTML: {html_path}")

        viewport = {
            "width": viewport_width or self.default_viewport["width"],
            "height": viewport_height or self.default_viewport["height"]
        }

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport=viewport)

            if self.disable_animations:
                await self._disable_animations(page)

            # Navigate to file
            file_url = f"file://{os.path.abspath(html_path)}"
            await page.goto(file_url, wait_until="networkidle")
            await page.wait_for_timeout(self.wait_for_fonts)

            # Screenshot
            if not output_path:
                output_path = html_path.replace(".html", "_screenshot.png")

            await page.screenshot(path=output_path, full_page=True)
            dom_tree = await page.content()

            await browser.close()

            return {
                "screenshot_path": output_path,
                "dom_tree": dom_tree,
                "url": file_url,
                "viewport": viewport
            }

    async def compare_multiple_viewports(
        self,
        project_path: str,
        viewports: list = None
    ) -> Dict[str, Dict]:
        """
        Render the same project at multiple viewport sizes
        Useful for responsive design verification

        Args:
            viewports: List of (width, height) tuples
                       Default: [(375, 667), (768, 1024), (1440, 900)]
        """
        if not viewports:
            viewports = [
                (375, 667),   # Mobile
                (768, 1024),  # Tablet
                (1440, 900)   # Desktop
            ]

        results = {}

        for width, height in viewports:
            device_name = self._get_device_name(width, height)
            print(f"\n📱 Rendering {device_name} ({width}x{height})...")

            result = await self.render(
                project_path,
                viewport_width=width,
                viewport_height=height
            )

            results[device_name] = result

        return results

    def _get_device_name(self, width: int, height: int) -> str:
        """Get friendly device name from dimensions"""
        if width < 600:
            return "mobile"
        elif width < 1000:
            return "tablet"
        else:
            return "desktop"


# Standalone test function
async def test_render_engine():
    """Test the render engine with a sample project"""
    print("🧪 Testing Render Engine\n")

    # Create a simple test HTML file
    test_dir = Path("test_render")
    test_dir.mkdir(exist_ok=True)

    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Test Page</title>
        <style>
            body {
                margin: 0;
                padding: 40px;
                font-family: system-ui, -apple-system, sans-serif;
            }
            .container {
                max-width: 800px;
                margin: 0 auto;
            }
            h1 {
                color: #3B82F6;
                font-size: 48px;
            }
            p {
                color: #6B7280;
                font-size: 18px;
                line-height: 1.6;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>GodComet Render Engine Test</h1>
            <p>This is a test page to verify the rendering pipeline works correctly.</p>
            <p>The Visual Auditor will compare this to the Figma design.</p>
        </div>
    </body>
    </html>
    """

    html_path = test_dir / "test.html"
    with open(html_path, "w") as f:
        f.write(html_content)

    engine = RenderEngine()
    result = await engine.render_static_html(str(html_path))

    print("\n📊 Render Results:")
    print(f"   Screenshot: {result['screenshot_path']}")
    print(f"   URL: {result['url']}")
    print(f"   Viewport: {result['viewport']}")


if __name__ == "__main__":
    asyncio.run(test_render_engine())
