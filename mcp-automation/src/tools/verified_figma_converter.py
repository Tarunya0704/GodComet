"""
Verified Figma Converter - The "VC-Fundable" Closed-Loop Pipeline
Figma → Code → Verify → Self-Heal → Deploy (Autonomous)

This is the MOAT that differentiates GodComet from Cursor/Copilot/v0.dev
"""

import os
import sys
import json
import asyncio
import time
from typing import Dict, Optional, List
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent.parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from verification.visual_auditor import VisualAuditor
from verification.render_engine import RenderEngine
from verification.self_healer import SelfHealer
from verification.confidence_scorer import ConfidenceScorer

# Import existing tools
from tools.production_figma_converter import ProductionFigmaToCode

# Optional tools (will handle gracefully if not available)
try:
    from tools.github_tool import GitHubTool
    GITHUB_AVAILABLE = True
except ImportError:
    GITHUB_AVAILABLE = False
    GitHubTool = None
    print("⚠️  GitHub tool not available (import failed)")

try:
    from tools.vercel_tool import VercelTool
    VERCEL_AVAILABLE = True
except ImportError:
    VERCEL_AVAILABLE = False
    VercelTool = None
    print("⚠️  Vercel tool not available (import failed)")


class VerifiedFigmaConverter:
    """
    Autonomous Figma-to-Production Pipeline with Visual Verification

    Pipeline:
    1. Extract Figma design + screenshot
    2. Generate React/Next.js code
    3. Render with Playwright
    4. Visual audit (compare Figma vs rendered)
    5. Self-heal if score < threshold
    6. Deploy to Vercel if passed
    7. Create GitHub repo

    This is what VCs want to see: GUARANTEED design fidelity
    """

    def __init__(
        self,
        threshold: float = 0.95,
        max_iterations: int = 3,
        auto_deploy: bool = True,
        use_openai: bool = True,
        use_anthropic: bool = False
    ):
        """
        Initialize Verified Converter

        Args:
            threshold: Minimum visual accuracy score to pass (default: 95%)
            max_iterations: Maximum self-healing attempts
            auto_deploy: Automatically deploy if verified
            use_openai: Use OpenAI GPT-4o for vision
            use_anthropic: Use Claude 3.5 Sonnet for vision
        """
        self.threshold = threshold
        self.max_iterations = max_iterations
        self.auto_deploy = auto_deploy

        # Initialize components
        self.visual_auditor = VisualAuditor(
            threshold=threshold,
            use_openai=use_openai,
            use_anthropic=use_anthropic
        )
        self.render_engine = RenderEngine()
        self.self_healer = SelfHealer(max_iterations=max_iterations)
        self.confidence_scorer = ConfidenceScorer()

        # Initialize existing tools
        figma_token = os.getenv("FIGMA_TOKEN")
        if not figma_token:
            print("⚠️  FIGMA_TOKEN not found in environment")
        self.figma_converter = ProductionFigmaToCode(figma_token) if figma_token else None

        # Tracking
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.iteration_history = []

    async def run(
        self,
        figma_url: str,
        project_name: Optional[str] = None,
        github_create: bool = True,
        vercel_deploy: bool = None
    ) -> Dict:
        """
        Main pipeline execution

        Returns:
            {
                "success": True/False,
                "final_score": 0.97,
                "iterations": 2,
                "project_path": "...",
                "github_url": "...",
                "vercel_url": "...",
                "timeline": [...],
                "recommendation": "deployed" | "needs_review"
            }
        """
        start_time = time.time()
        vercel_deploy = vercel_deploy if vercel_deploy is not None else self.auto_deploy

        print("=" * 80)
        print("🚀 GODCOMET VERIFIED FIGMA CONVERTER")
        print("=" * 80)
        print(f"📋 Session ID: {self.session_id}")
        print(f"🎯 Target Accuracy: {self.threshold:.0%}")
        print(f"🔄 Max Iterations: {self.max_iterations}")
        print(f"🌐 Auto-Deploy: {vercel_deploy}")
        print("=" * 80)

        timeline = []

        try:
            # STEP 1: Extract Figma Design
            print("\n📐 STEP 1: Extracting Figma Design...")
            step_start = time.time()

            figma_result = await self._extract_figma_design(figma_url, project_name)
            figma_screenshot_path = figma_result["screenshot_path"]
            figma_metadata = figma_result["metadata"]
            original_prompt = figma_result["prompt"]

            step_duration = time.time() - step_start
            timeline.append({
                "step": "figma_extraction",
                "duration": step_duration,
                "status": "completed"
            })
            print(f"   ✅ Completed in {step_duration:.1f}s")

            # STEP 2: Generate Initial Code
            print("\n💻 STEP 2: Generating React Code...")
            step_start = time.time()

            code_result = await self._generate_code(
                figma_metadata,
                original_prompt,
                project_name
            )
            project_path = code_result["project_path"]

            step_duration = time.time() - step_start
            timeline.append({
                "step": "code_generation",
                "duration": step_duration,
                "status": "completed",
                "project_path": project_path
            })
            print(f"   ✅ Completed in {step_duration:.1f}s")

            # STEP 3-5: Verify and Self-Heal Loop
            print("\n🔄 STARTING VERIFICATION LOOP...")
            print("=" * 80)

            loop_result = await self._verification_loop(
                project_path,
                figma_screenshot_path,
                figma_metadata,
                original_prompt,
                timeline
            )

            final_score = loop_result["final_score"]
            passed = loop_result["passed"]
            iterations = loop_result["iterations"]

            # STEP 6: Deploy (if passed)
            github_url = None
            vercel_url = None

            if passed and vercel_deploy:
                print("\n🚀 STEP 6: Deploying to Production...")
                step_start = time.time()

                deploy_result = await self._deploy_to_production(
                    project_path,
                    project_name or "godcomet-verified",
                    github_create
                )

                github_url = deploy_result.get("github_url")
                vercel_url = deploy_result.get("vercel_url")

                step_duration = time.time() - step_start
                timeline.append({
                    "step": "deployment",
                    "duration": step_duration,
                    "status": "completed",
                    "github_url": github_url,
                    "vercel_url": vercel_url
                })
                print(f"   ✅ Deployed in {step_duration:.1f}s")

            # Final Summary
            total_duration = time.time() - start_time

            print("\n" + "=" * 80)
            print("📊 FINAL RESULTS")
            print("=" * 80)
            print(f"✅ Success: {passed}")
            print(f"📈 Final Score: {final_score:.1%}")
            print(f"🔄 Iterations: {iterations}")
            print(f"⏱️  Total Time: {total_duration:.1f}s")
            if github_url:
                print(f"🐙 GitHub: {github_url}")
            if vercel_url:
                print(f"🌐 Vercel: {vercel_url}")
            print("=" * 80)

            return {
                "success": passed,
                "final_score": final_score,
                "iterations": iterations,
                "project_path": project_path,
                "github_url": github_url,
                "vercel_url": vercel_url,
                "timeline": timeline,
                "total_duration": total_duration,
                "recommendation": "deployed" if passed and vercel_url else "needs_review",
                "session_id": self.session_id,
                "iteration_history": self.iteration_history
            }

        except Exception as e:
            print(f"\n❌ Pipeline failed: {e}")
            import traceback
            traceback.print_exc()

            return {
                "success": False,
                "error": str(e),
                "timeline": timeline,
                "session_id": self.session_id
            }

    async def _extract_figma_design(
        self,
        figma_url: str,
        project_name: Optional[str]
    ) -> Dict:
        """Step 1: Extract Figma design and capture screenshot"""
        print(f"   🔗 Figma URL: {figma_url}")

        # Use existing Figma converter to extract design
        # TODO: Modify production_figma_converter.py to also return screenshot
        # For now, we'll simulate this

        # Extract Figma file ID and node ID
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(figma_url)
        file_id = parsed.path.split('/')[2] if len(parsed.path.split('/')) > 2 else None
        node_id = parse_qs(parsed.query).get('node-id', [None])[0]

        if not file_id:
            raise ValueError(f"Invalid Figma URL: {figma_url}")

        # Get Figma design data
        figma_api_token = os.getenv("FIGMA_TOKEN")
        if not figma_api_token:
            raise ValueError("FIGMA_TOKEN not found in environment")

        import requests
        headers = {"X-Figma-Token": figma_api_token}

        # Get file data
        file_url = f"https://api.figma.com/v1/files/{file_id}"
        if node_id:
            file_url += f"?ids={node_id}"

        response = requests.get(file_url, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f"Figma API error: {response.status_code}")

        figma_data = response.json()

        # Get screenshot (export as PNG)
        screenshot_url = f"https://api.figma.com/v1/images/{file_id}"
        params = {
            "ids": node_id if node_id else list(figma_data["document"]["children"][0]["children"][0]["id"])[0],
            "format": "png",
            "scale": 2
        }
        response = requests.get(screenshot_url, headers=headers, params=params)
        image_data = response.json()

        # Download screenshot
        image_url = list(image_data["images"].values())[0]
        image_response = requests.get(image_url)

        # Save screenshot
        screenshots_dir = Path("screenshots") / self.session_id
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = screenshots_dir / "figma_original.png"

        with open(screenshot_path, "wb") as f:
            f.write(image_response.content)

        print(f"   📸 Screenshot saved: {screenshot_path}")

        return {
            "screenshot_path": str(screenshot_path),
            "metadata": {
                "file_id": file_id,
                "node_id": node_id,
                "figma_url": figma_url,
                "design_data": figma_data
            },
            "prompt": f"Generate a React/Next.js website from Figma design: {figma_url}"
        }

    async def _generate_code(
        self,
        figma_metadata: Dict,
        prompt: str,
        project_name: Optional[str]
    ) -> Dict:
        """Step 2: Generate React/Next.js code"""
        print(f"   🤖 Using AI to generate code...")

        if not self.figma_converter:
            raise ValueError("Figma converter not initialized. Please set FIGMA_TOKEN in .env")

        # Use existing Figma converter
        figma_url = figma_metadata["figma_url"]

        # Create output directory
        projects_dir = Path(__file__).parent.parent.parent / "projects"
        if not project_name:
            project_name = f"figma_project_{self.session_id}"

        output_dir = projects_dir / project_name
        output_dir.mkdir(parents=True, exist_ok=True)

        # This will generate code (async method)
        result = await self.figma_converter.convert(
            figma_url=figma_url,
            output_dir=output_dir
        )

        project_path = str(output_dir)
        print(f"   📁 Project created: {project_path}")

        return {
            "project_path": project_path,
            "result": result
        }

    async def _verification_loop(
        self,
        project_path: str,
        figma_screenshot_path: str,
        figma_metadata: Dict,
        original_prompt: str,
        timeline: List[Dict]
    ) -> Dict:
        """Steps 3-5: Render, Verify, Self-Heal (loop up to max_iterations)"""

        previous_score = 0.0
        self.self_healer.reset_iteration_count()

        for iteration in range(1, self.max_iterations + 1):
            print(f"\n🔄 ITERATION {iteration}/{self.max_iterations}")
            print("-" * 80)

            # Step 3: Render Generated Code
            print(f"   🎬 Rendering code with Playwright...")
            render_start = time.time()

            render_result = await self.render_engine.render(
                project_path,
                output_path=f"screenshots/{self.session_id}/rendered_iter{iteration}.png"
            )

            rendered_screenshot = render_result["screenshot_path"]
            render_duration = time.time() - render_start
            print(f"   ✅ Rendered in {render_duration:.1f}s")

            # Step 4: Visual Audit
            print(f"   🔍 Running visual audit...")
            audit_start = time.time()

            audit_result = self.visual_auditor.audit(
                figma_screenshot_path,
                rendered_screenshot,
                figma_metadata
            )

            current_score = audit_result["score"]
            passed = audit_result["passed"]
            audit_duration = time.time() - audit_start

            print(f"   📊 Score: {current_score:.1%} (threshold: {self.threshold:.0%})")
            print(f"   ✅ Audit completed in {audit_duration:.1f}s")

            # Track iteration
            iteration_data = {
                "iteration": iteration,
                "render_duration": render_duration,
                "audit_duration": audit_duration,
                "score": current_score,
                "passed": passed,
                "issues_count": len(audit_result["issues"]),
                "screenshot": rendered_screenshot
            }
            self.iteration_history.append(iteration_data)

            timeline.append({
                "step": f"verification_iteration_{iteration}",
                "duration": render_duration + audit_duration,
                "status": "passed" if passed else "failed",
                "score": current_score
            })

            # Log full score history so improvement is visible across iterations
            history_scores = [h["score"] for h in self.iteration_history]
            history_str = " → ".join(f"{s:.1%}" for s in history_scores)
            print(f"   📈 Score history: [{history_str}]")

            # Check if passed the deployment threshold
            if passed:
                print(f"   ✅ PASSED! Score {current_score:.1%} meets threshold {self.threshold:.0%}")
                return {
                    "final_score": current_score,
                    "passed": True,
                    "iterations": iteration,
                    "final_audit": audit_result
                }

            # Early-stop: score is good enough — avoid burning more API calls on healing
            HEALING_THRESHOLD = 0.85
            if current_score >= HEALING_THRESHOLD:
                print(f"   ✅ Score {current_score:.1%} ≥ healing threshold ({HEALING_THRESHOLD:.0%}), stopping early")
                return {
                    "final_score": current_score,
                    "passed": False,
                    "iterations": iteration,
                    "final_audit": audit_result
                }

            # Check if max iterations reached
            if iteration >= self.max_iterations:
                print(f"   ⚠️  Max iterations ({self.max_iterations}) reached")
                return {
                    "final_score": current_score,
                    "passed": False,
                    "iterations": iteration,
                    "final_audit": audit_result
                }

            # Step 5: Self-Heal
            print(f"\n   🔧 Self-healing (attempt {iteration})...")

            # Analyze improvement from previous iteration
            if iteration > 1:
                improvement = self.self_healer.analyze_improvement(
                    previous_score,
                    current_score
                )
                print(f"   📈 Improvement: {improvement['delta']:+.1%}")

                if improvement["recommendation"] == "stop":
                    print(f"   ⚠️  Score got worse, stopping self-heal")
                    return {
                        "final_score": current_score,
                        "passed": False,
                        "iterations": iteration,
                        "final_audit": audit_result
                    }

            # Generate healing prompt
            healing_prompt = self.self_healer.generate_healing_prompt(
                original_prompt,
                audit_result,
                figma_metadata
            )

            # Regenerate code with healing prompt
            print(f"   🤖 Regenerating code with corrections...")
            heal_start = time.time()

            healed = await self._regenerate_code_with_healing(
                project_path=project_path,
                figma_screenshot_path=figma_screenshot_path,
                rendered_screenshot_path=rendered_screenshot,
                audit_result=audit_result,
                healing_prompt=healing_prompt
            )

            heal_duration = time.time() - heal_start

            if not healed:
                print(f"   ⚠️  Healing unavailable (Groq key missing or call failed), stopping at iteration {iteration}")
                return {
                    "final_score": current_score,
                    "passed": False,
                    "iterations": iteration,
                    "final_audit": audit_result
                }

            print(f"   ✅ Code regenerated in {heal_duration:.1f}s")

            previous_score = current_score

        # If we get here, all iterations failed
        return {
            "final_score": current_score,
            "passed": False,
            "iterations": self.max_iterations,
            "final_audit": audit_result
        }

    async def _regenerate_code_with_healing(
        self,
        project_path: str,
        figma_screenshot_path: str,
        rendered_screenshot_path: str,
        audit_result: Dict,
        healing_prompt: str
    ) -> bool:
        """
        Regenerate project TSX files guided by the visual diff between Figma and
        the current rendered output.

        Sends both screenshots + all current TSX files to Groq vision, asks it to
        fix ONLY the components that look wrong, then writes the response back to
        disk so the next render iteration picks up the changes.

        Returns True on success, False if Groq is unavailable or the call fails.
        """
        import base64
        import re as _re

        # --- Groq client (same pattern as AICodeGenerator) ---
        try:
            from groq import Groq
        except ImportError:
            print("   ⚠️  groq package not installed, cannot self-heal")
            return False

        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            print("   ⚠️  GROQ_API_KEY not set, cannot self-heal")
            return False

        groq_client = Groq(api_key=api_key)
        model = "meta-llama/llama-4-scout-17b-16e-instruct"

        # --- Collect current TSX files ---
        project = Path(project_path)
        tsx_files: Dict[str, str] = {}

        # Root page file
        for candidate in [
            project / "src" / "app" / "page.tsx",
            project / "src" / "pages" / "index.tsx",
        ]:
            if candidate.exists():
                tsx_files[str(candidate.relative_to(project))] = candidate.read_text(encoding="utf-8")
                break

        # Component files
        components_dir = project / "src" / "components"
        if components_dir.exists():
            for f in sorted(components_dir.glob("*.tsx")):
                tsx_files[str(f.relative_to(project))] = f.read_text(encoding="utf-8")

        if not tsx_files:
            print("   ⚠️  No TSX files found in project, cannot self-heal")
            return False

        # --- Encode both screenshots to base64 (same as visual_auditor._encode_image) ---
        def _encode(path: str) -> str:
            with open(path, "rb") as fh:
                return base64.b64encode(fh.read()).decode()

        figma_b64 = _encode(figma_screenshot_path)
        rendered_b64 = _encode(rendered_screenshot_path)

        # --- Summarise audit issues (capped to keep within token budget) ---
        issues = audit_result.get("issues", [])
        critical = [i for i in issues if i.get("severity") == "critical"]
        minor = [i for i in issues if i.get("severity") not in ("critical",)]

        issues_text = ""
        if critical:
            issues_text += "CRITICAL (must fix):\n"
            for iss in critical:
                fix = f" → Fix: {iss['fix']}" if iss.get("fix") else ""
                issues_text += (
                    f"  • {iss.get('type','?')} on <{iss.get('element','?')}>: "
                    f"expected {iss.get('expected','?')}, got {iss.get('actual','?')}{fix}\n"
                )
        if minor:
            issues_text += "MINOR (should fix):\n"
            for iss in minor[:5]:  # Cap to avoid token bloat
                issues_text += (
                    f"  • {iss.get('type','?')} on <{iss.get('element','?')}>: "
                    f"expected {iss.get('expected','?')}, got {iss.get('actual','?')}\n"
                )

        # --- Build code block string ---
        code_context = ""
        for rel_path, code in tsx_files.items():
            code_context += f"\n=== {rel_path} ===\n{code}\n"

        system_text = (
            "You are a React/Next.js UI engineer fixing visual mismatches.\n"
            "Image 1 = Figma reference (target). Image 2 = current rendered output (needs fixing).\n"
            "Fix ONLY the components that differ from the Figma reference. "
            "Leave working sections untouched.\n"
            "Return ONLY the changed files. Each file MUST start with its relative path marker:\n"
            "  === src/app/page.tsx ===\n"
            "Then the full corrected file content — no markdown fences, no explanation.\n"
            "Omit any file that needs no changes."
        )

        user_content = [
            {"type": "text", "text": "Figma Reference (target):"},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{figma_b64}"}},
            {"type": "text", "text": "Current Rendered Output (needs fixing):"},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{rendered_b64}"}},
            {
                "type": "text",
                "text": (
                    f"Visual issues to fix:\n{issues_text}\n"
                    f"Additional context:\n{healing_prompt}\n\n"
                    f"Current project code:\n{code_context}\n\n"
                    "Return the corrected file(s) now."
                ),
            },
        ]

        # --- Groq vision call (same pattern as AICodeGenerator.generate_component) ---
        try:
            response = groq_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_text},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.1,
                max_tokens=8000,
            )
        except Exception as e:
            print(f"   ⚠️  Groq healing call failed: {e}")
            return False

        raw = response.choices[0].message.content

        # --- Parse "=== path ===" file blocks from response ---
        parts = _re.split(r'^=== (.+?) ===\s*$', raw, flags=_re.MULTILINE)
        # parts = ['prefix', 'path1', 'code1', 'path2', 'code2', ...]

        if len(parts) < 3:
            # No markers — try writing the whole response to the root page as fallback
            root_rel = list(tsx_files.keys())[0]
            code = _re.sub(r'^```[^\n]*\n|```$', '', raw.strip(), flags=_re.MULTILINE).strip()
            if "export default" in code:
                (project / root_rel).write_text(code, encoding="utf-8")
                print(f"   💾 (fallback) Healed code written to {root_rel}")
                return True
            print("   ⚠️  Groq response had no file markers and no valid TSX — skipping write")
            return False

        written: List[str] = []
        for i in range(1, len(parts) - 1, 2):
            rel_path = parts[i].strip()
            code = parts[i + 1].strip()
            # Strip accidental markdown fences
            code = _re.sub(r'^```[^\n]*\n|```$', '', code, flags=_re.MULTILINE).strip()
            if not code:
                continue
            dest = project / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(code, encoding="utf-8")
            written.append(rel_path)

        if written:
            print(f"   💾 Healed files written: {', '.join(written)}")
            return True

        print("   ⚠️  Groq returned file markers but all code blocks were empty")
        return False

    async def _deploy_to_production(
        self,
        project_path: str,
        project_name: str,
        create_github: bool
    ) -> Dict:
        """Step 6: Deploy to GitHub and Vercel"""
        github_url = None
        vercel_url = None

        try:
            # Create GitHub repo and push code
            if create_github and GITHUB_AVAILABLE:
                github_token = os.getenv("GITHUB_TOKEN")
                if github_token:
                    print(f"   🐙 Creating GitHub repository...")
                    try:
                        github_tool = GitHubTool(access_token=github_token)
                        # Use build_and_push_project for complete workflow
                        github_result = await github_tool.build_and_push_project(
                            repo_name=project_name,
                            description="Generated with GodComet Verified Converter",
                            local_path=project_path,
                            branch="main"
                        )
                        if github_result.get("success"):
                            github_url = github_result.get("data", {}).get("repo_url")
                            print(f"   ✅ GitHub repo: {github_url}")
                        else:
                            print(f"   ⚠️  GitHub: {github_result.get('error', 'Unknown error')}")
                    except Exception as e:
                        print(f"   ⚠️  GitHub creation failed: {e}")
                else:
                    print(f"   ⚠️  GITHUB_TOKEN not found, skipping repo creation")
            elif create_github and not GITHUB_AVAILABLE:
                print(f"   ⚠️  GitHub tool not available, skipping repo creation")

            # Deploy to Vercel
            if VERCEL_AVAILABLE:
                vercel_token = os.getenv("VERCEL_TOKEN")
                print(f"   🌐 Deploying to Vercel...")
                try:
                    vercel_tool = VercelTool(token=vercel_token)
                    vercel_result = await vercel_tool.deploy(
                        local_path=project_path,
                        production=True
                    )
                    if vercel_result.get("success"):
                        vercel_url = vercel_result.get("data", {}).get("url")
                        print(f"   ✅ Vercel URL: {vercel_url}")
                    else:
                        print(f"   ⚠️  Vercel: {vercel_result.get('error', 'Unknown error')}")
                except Exception as e:
                    print(f"   ⚠️  Vercel deployment failed: {e}")
            else:
                print(f"   ⚠️  Vercel tool not available, skipping deployment")
                print(f"   📁 Project ready at: {project_path}")

            return {
                "github_url": github_url,
                "vercel_url": vercel_url
            }

        except Exception as e:
            print(f"   ⚠️  Deployment error: {e}")
            return {
                "github_url": github_url,
                "vercel_url": vercel_url,
                "error": str(e)
            }


# Standalone CLI
async def main():
    """CLI entry point for testing"""
    import argparse

    parser = argparse.ArgumentParser(description="GodComet Verified Figma Converter")
    parser.add_argument("figma_url", help="Figma design URL")
    parser.add_argument("--name", help="Project name", default=None)
    parser.add_argument("--threshold", type=float, default=0.95, help="Visual accuracy threshold")
    parser.add_argument("--max-iter", type=int, default=3, help="Max healing iterations")
    parser.add_argument("--no-deploy", action="store_true", help="Skip deployment")
    parser.add_argument("--use-claude", action="store_true", help="Use Claude vision instead of GPT-4o")

    args = parser.parse_args()

    converter = VerifiedFigmaConverter(
        threshold=args.threshold,
        max_iterations=args.max_iter,
        auto_deploy=not args.no_deploy,
        use_openai=not args.use_claude,
        use_anthropic=args.use_claude
    )

    result = await converter.run(
        figma_url=args.figma_url,
        project_name=args.name
    )

    # Save result to JSON
    output_file = f"verified_result_{converter.session_id}.json"
    with open(output_file, "w") as f:
        json.dump(result, f, indent=2, default=str)

    print(f"\n📄 Full results saved to: {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
