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
        Main render function.

        Strategy (fastest → slowest):
          1. Static export: npm run build → open out/index.html with file:// (no server needed)
          2. Dev server fallback: npm run dev → http://localhost:PORT

        Returns:
            {
                "screenshot_path": "/path/to/screenshot.png",
                "dom_tree": "<html>...</html>",
                "url": "...",
                "viewport": {"width": 1440, "height": 900},
                "metadata": {...}
            }
        """
        print(f"🎬 Starting render pipeline for: {project_path}")

        viewport = {
            "width": viewport_width or self.default_viewport["width"],
            "height": viewport_height or self.default_viewport["height"]
        }

        # Step 1: Build / start server
        server_url, server_process = await self._start_dev_server(project_path)
        is_file_url = server_url.startswith("file://")
        print(f"   🌐 {'Static file' if is_file_url else 'Dev server'}: {server_url[:80]}")

        try:
            # Step 2: Launch browser and navigate
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        '--disable-web-security',
                        '--disable-features=IsolateOrigins,site-per-process',
                        '--allow-file-access-from-files',   # Needed for file:// URLs
                    ]
                )

                page = await browser.new_page(viewport=viewport)

                if self.disable_animations:
                    await self._disable_animations(page)

                # file:// pages don't have network requests — use "load" not "networkidle"
                wait_until = "load" if is_file_url else "networkidle"
                print(f"   🔗 Navigating ({wait_until})...")
                await page.goto(server_url, wait_until=wait_until, timeout=60000)

                await page.wait_for_timeout(self.wait_for_fonts)

                # Step 3: Capture screenshot
                if not output_path:
                    output_dir = Path(project_path) / "screenshots"
                    output_dir.mkdir(exist_ok=True)
                    timestamp = int(time.time())
                    output_path = str(output_dir / f"render_{timestamp}.png")

                await page.screenshot(
                    path=output_path,
                    full_page=full_page,
                    type="png"
                )
                print(f"   📸 Screenshot saved: {output_path}")

                dom_tree = await page.content()
                accessibility_tree = await self._get_accessibility_tree(page)
                await browser.close()

                print(f"   ✅ Render complete!")
                return {
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

        finally:
            await self._stop_dev_server(server_process)

    async def _start_dev_server(self, project_path: str) -> Tuple[str, Optional[subprocess.Popen]]:
        """
        Build project and return URL to render.

        Strategy:
          1. Static export: `npm run build` → file://...out/index.html  (fast, no server)
          2. Dev server fallback: `npm run dev` (slow, last resort)
        """
        project_dir = Path(project_path)

        package_json = project_dir / "package.json"
        if not package_json.exists():
            raise FileNotFoundError(f"package.json not found in {project_path}")

        # Install dependencies if needed
        node_modules = project_dir / "node_modules"
        if not node_modules.exists():
            print(f"   📦 Installing dependencies (first time, may take ~2 min)...")
            install_result = subprocess.run(
                ["npm", "install", "--prefer-offline", "--no-audit"],
                cwd=str(project_dir),
                capture_output=True,
                text=True,
                shell=True,
                timeout=300
            )
            if install_result.returncode != 0:
                print(f"   ⚠️  npm install stderr: {install_result.stderr[:300]}")

        # ── Strategy 1: Static export (next build → out/) ──────────────────
        print(f"   🏗️  Building static export (npm run build)...")
        build_result = subprocess.run(
            ["npm", "run", "build"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            shell=True,
            timeout=300,
            env={**os.environ, "CI": "false"}   # CI=false suppresses warning-as-error
        )

        if build_result.returncode == 0:
            out_dir = project_dir / "out"
            index_html = out_dir / "index.html"
            if index_html.exists():
                # Convert Windows backslash path to forward slashes for file:// URL
                file_url = "file:///" + index_html.as_posix()
                print(f"   ✅ Static build succeeded → {file_url}")
                return file_url, None   # No server process to manage
        else:
            print(f"   ⚠️  Static build failed (rc={build_result.returncode}). stderr:")
            print(f"       {build_result.stderr[:500]}")
            print(f"   ↩️  Falling back to dev server...")

        # ── Strategy 2: Dev server fallback ────────────────────────────────
        port = self._find_available_port(3000)
        print(f"   🚀 Starting dev server on port {port}...")

        env = {**os.environ, "PORT": str(port)}
        server_process = subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=str(project_dir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=True
        )

        server_url = f"http://127.0.0.1:{port}"
        max_wait = 120
        waited = 0

        while waited < max_wait:
            try:
                import requests
                response = requests.get(server_url, timeout=2)
                if response.status_code in (200, 404):
                    print(f"   ✅ Dev server ready after {waited}s")
                    break
            except Exception:
                pass

            await asyncio.sleep(1)
            waited += 1

            if server_process.poll() is not None:
                stderr = server_process.stderr.read()
                raise RuntimeError(f"Dev server process exited unexpectedly: {stderr[:500]}")

        if waited >= max_wait:
            try:
                stderr_out = server_process.stderr.read(2000) if server_process.stderr else ""
                print(f"   ❌ Server stderr: {stderr_out}")
            except Exception:
                pass
            server_process.kill()
            raise TimeoutError(f"Dev server did not respond within {max_wait}s on port {port}")

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
