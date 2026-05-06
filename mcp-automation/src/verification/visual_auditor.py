"""
Visual Auditor - Compare Figma designs to rendered code using Vision LLMs
This is the core "moat" that guarantees design fidelity
"""

import os
import re
import json
import logging
import base64
from typing import Dict, List, Tuple, Optional
from pathlib import Path
from PIL import Image, ImageChops
import numpy as np

logger = logging.getLogger(__name__)
try:
    from skimage.metrics import structural_similarity as ssim
    import skimage
    SKIMAGE_AVAILABLE = True
except ImportError:
    SKIMAGE_AVAILABLE = False
import io
from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent.parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# Vision API clients
try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

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


class VisualAuditor:
    """
    Compares Figma screenshots to rendered code screenshots
    Returns confidence score and actionable diff report
    """

    def __init__(
        self,
        threshold: float = 0.95,
        use_groq: bool = True,
        use_openai: bool = False,
        use_anthropic: bool = True,
        groq_model: str = "meta-llama/llama-4-scout-17b-16e-instruct",
        openai_model: str = "gpt-4o",
        anthropic_model: str = "claude-sonnet-4-20250514"
    ):
        """
        Initialize Visual Auditor with configurable thresholds and models

        Args:
            threshold: Minimum confidence score to pass (0.0-1.0)
            use_groq: Use Groq Llama 3.2 Vision for analysis (FREE, FAST) - DEFAULT
            use_openai: Use OpenAI GPT-4o for vision analysis
            use_anthropic: Use Anthropic Claude for vision analysis
            groq_model: Groq model ID (meta-llama/llama-4-scout-17b-16e-instruct)
            openai_model: OpenAI model ID
            anthropic_model: Anthropic model ID
        """
        self.threshold = threshold
        self.use_groq = use_groq
        self.use_openai = use_openai
        self.use_anthropic = use_anthropic

        # Initialize API clients
        self.groq_client = None
        self.openai_client = None
        self.anthropic_client = None

        # Try Groq first (FREE and FAST!)
        if use_groq and GROQ_AVAILABLE:
            api_key = os.getenv("GROQ_API_KEY")
            if api_key:
                self.groq_client = Groq(api_key=api_key)
                self.groq_model = groq_model
                print(f"✅ Groq Vision enabled ({groq_model})")
            else:
                print("⚠️  GROQ_API_KEY not found, Groq vision disabled")

        if use_openai and OPENAI_AVAILABLE:
            api_key = os.getenv("OPENAI_API_KEY")
            if api_key:
                self.openai_client = OpenAI(api_key=api_key)
                self.openai_model = openai_model
                print(f"✅ OpenAI Vision enabled ({openai_model})")
            else:
                print("⚠️  OPENAI_API_KEY not found, OpenAI vision disabled")

        if use_anthropic and ANTHROPIC_AVAILABLE:
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if api_key:
                self.anthropic_client = Anthropic(api_key=api_key)
                self.anthropic_model = anthropic_model
                print(f"✅ Anthropic Vision enabled ({anthropic_model})")
            else:
                print("⚠️  ANTHROPIC_API_KEY not found, Claude vision disabled")

        # Check if any vision model is available
        if not self.groq_client and not self.openai_client and not self.anthropic_client:
            print("⚠️  No vision models available, using structural comparison only")

    def audit(
        self,
        figma_screenshot_path: str,
        rendered_screenshot_path: str,
        figma_metadata: Optional[Dict] = None
    ) -> Dict:
        """
        Main audit function - compares two images and returns detailed report

        Returns:
            {
                "score": 0.97,
                "passed": True,
                "structural_score": 0.95,
                "pixel_score": 0.96,
                "vision_score": 0.98,
                "issues": [
                    {"type": "color_mismatch", "element": "button", "severity": "minor", ...}
                ],
                "recommendations": [...]
            }
        """
        print(f"🔍 Starting visual audit...")
        print(f"   Figma: {figma_screenshot_path}")
        print(f"   Rendered: {rendered_screenshot_path}")

        # Step 1: Load and preprocess images
        figma_img, rendered_img = self._load_and_preprocess(
            figma_screenshot_path,
            rendered_screenshot_path
        )

        # Step 2: Structural similarity (SSIM)
        structural_score = self._calculate_ssim(figma_img, rendered_img)
        print(f"   📊 Structural Score: {structural_score:.2%}")

        # Step 3: Pixel-wise difference
        pixel_score = self._calculate_pixel_similarity(figma_img, rendered_img)
        print(f"   🎨 Pixel Score: {pixel_score:.2%}")

        # Step 4: Vision LLM analysis (if available)
        vision_result = self._vision_analysis(
            figma_screenshot_path,
            rendered_screenshot_path,
            figma_metadata
        )
        vision_score = vision_result.get("score", 0.0)
        print(f"   👁️  Vision Score: {vision_score:.2%}")

        # Step 5: Calculate weighted overall score
        overall_score = self._calculate_overall_score(
            structural_score,
            pixel_score,
            vision_score
        )

        # Step 6: Compile issues and recommendations
        issues = vision_result.get("issues", [])
        recommendations = self._generate_recommendations(
            structural_score,
            pixel_score,
            vision_score,
            issues
        )

        result = {
            "score": overall_score,
            "passed": overall_score >= self.threshold,
            "threshold": self.threshold,
            "structural_score": structural_score,
            "pixel_score": pixel_score,
            "vision_score": vision_score,
            "issues": issues,
            "recommendations": recommendations,
            "metadata": {
                "figma_path": figma_screenshot_path,
                "rendered_path": rendered_screenshot_path,
                "figma_metadata": figma_metadata
            }
        }

        print(f"\n   ✅ Overall Score: {overall_score:.2%} {'PASS' if result['passed'] else 'FAIL'}")
        print(f"   📋 Issues Found: {len(issues)}")

        return result

    def _load_and_preprocess(
        self,
        figma_path: str,
        rendered_path: str
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Load images and ensure they're the same size.

        If aspect ratios differ by more than 10%, the images represent
        fundamentally different viewports (e.g. thumbnail vs frame render).
        In that case we resize BOTH to a common target (rendered width) to
        avoid meaningless SSIM comparisons caused by stretching.
        """
        figma_img = Image.open(figma_path).convert("RGB")
        rendered_img = Image.open(rendered_path).convert("RGB")

        fw, fh = figma_img.size
        rw, rh = rendered_img.size

        if figma_img.size != rendered_img.size:
            figma_ar = fw / fh if fh else 1.0
            rendered_ar = rw / rh if rh else 1.0
            ar_diff = abs(figma_ar - rendered_ar) / max(figma_ar, rendered_ar)

            if ar_diff > 0.10:
                # Aspect ratios differ significantly — intelligently crop the figma
                # image to match the rendered AR before resizing.
                # figma_ar < rendered_ar  → figma is too tall (extra content at TOP, e.g. guidelines text)
                #   → crop from top, keep the bottom portion
                # figma_ar > rendered_ar  → figma is too wide (extra content on sides)
                #   → crop horizontally centered
                print(
                    f"   ⚠️  Aspect ratio mismatch ({fw}×{fh} AR={figma_ar:.2f} vs "
                    f"{rw}×{rh} AR={rendered_ar:.2f}, diff={ar_diff*100:.0f}%)."
                )
                if figma_ar < rendered_ar:
                    # Figma image is too tall — crop top (frame is at the bottom)
                    crop_h = int(fw / rendered_ar)
                    crop_h = min(crop_h, fh)
                    crop_top = fh - crop_h
                    figma_img = figma_img.crop((0, crop_top, fw, fh))
                    print(f"   ✂️  Cropped figma: removed top {crop_top}px (extra content above frame) → {fw}×{crop_h}")
                else:
                    # Figma image is too wide — crop sides centered
                    crop_w = int(fh * rendered_ar)
                    crop_w = min(crop_w, fw)
                    crop_left = (fw - crop_w) // 2
                    figma_img = figma_img.crop((crop_left, 0, crop_left + crop_w, fh))
                    print(f"   ✂️  Cropped figma: removed {crop_left}px from each side → {crop_w}×{fh}")

                figma_img = figma_img.resize((rw, rh), Image.Resampling.LANCZOS)
                print(f"   ⚙️  Resized cropped figma to rendered dimensions {rw}×{rh}")
                # rendered_img is already the right size
            else:
                print(f"   ⚙️  Resizing rendered: {rw}×{rh} → {fw}×{fh}")
                rendered_img = rendered_img.resize((fw, fh), Image.Resampling.LANCZOS)

        return np.array(figma_img), np.array(rendered_img)

    def _calculate_ssim(self, img1: np.ndarray, img2: np.ndarray) -> float:
        """Calculate Structural Similarity Index (SSIM)"""
        if not SKIMAGE_AVAILABLE:
            return {"score": None, "method": "skimage_unavailable"}
        try:
            # Convert to grayscale for SSIM
            from skimage.color import rgb2gray
            gray1 = rgb2gray(img1)
            gray2 = rgb2gray(img2)

            score = ssim(
                gray1,
                gray2,
                data_range=gray1.max() - gray1.min()
            )
            return float(score)
        except Exception as e:
            print(f"   ⚠️  SSIM calculation failed: {e}")
            return 0.0

    def _calculate_pixel_similarity(self, img1: np.ndarray, img2: np.ndarray) -> float:
        """Calculate pixel-wise similarity (inverse of normalized difference)"""
        try:
            diff = np.abs(img1.astype(float) - img2.astype(float))
            total_diff = np.sum(diff)
            max_diff = img1.size * 255  # Max possible difference
            similarity = 1.0 - (total_diff / max_diff)
            return float(similarity)
        except Exception as e:
            print(f"   ⚠️  Pixel similarity calculation failed: {e}")
            return 0.0

    def _vision_analysis(
        self,
        figma_path: str,
        rendered_path: str,
        figma_metadata: Optional[Dict]
    ) -> Dict:
        """Pixel-diff score + optional Claude/Groq issue extraction for healer feedback."""
        pixel_score, _ = self._pixel_diff_score(figma_path, rendered_path)

        # If Anthropic available and score is below 90%, run vision analysis to get specific issues
        issues: List[Dict] = []
        if pixel_score < 0.90 and self.anthropic_client:
            try:
                figma_b64 = self._encode_image(figma_path, max_width=1024)
                rendered_b64 = self._encode_image(rendered_path, max_width=1024)
                prompt = (
                    "Compare these two UI screenshots (Figma design vs rendered code) and list every visual difference.\n"
                    "For EACH difference output a JSON object like:\n"
                    '{"type":"color_mismatch","element":"sidebar background","severity":"critical","expected":"#1a1a2e","actual":"#ffffff","fix":"change bg-white to bg-[#1a1a2e]"}\n\n'
                    "severity: 'critical' for missing elements or wrong layout, 'major' for wrong colors/sizes, 'minor' for spacing.\n"
                    "Return ONLY a JSON array of issue objects. No text, no markdown."
                )
                response = self.anthropic_client.messages.create(
                    model=self.anthropic_model,
                    max_tokens=2048,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Target Figma design:"},
                            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": figma_b64}},
                            {"type": "text", "text": "Rendered code output:"},
                            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": rendered_b64}},
                            {"type": "text", "text": prompt},
                        ]
                    }]
                )
                raw = response.content[0].text.strip()
                # Strip markdown fences
                if "```" in raw:
                    m = re.search(r'```(?:json)?\n?(.*?)```', raw, re.DOTALL)
                    if m:
                        raw = m.group(1).strip()
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    issues = parsed
                    logger.info(f"[AUDIT] Claude vision found {len(issues)} issues")
            except Exception as e:
                logger.warning(f"[AUDIT] Claude vision issue analysis failed: {e}")

        return {"score": pixel_score, "issues": issues}

    def _pixel_diff_score(self, figma_path: str, rendered_path: str) -> Tuple[float, List]:
        """Compare two images with pixelmatch (PIL contrib) and return (match_ratio, [])."""
        try:
            from pixelmatch.contrib.PIL import pixelmatch as _pm
        except ImportError:
            logger.warning("[VISION] pixelmatch not installed — vision score = 0")
            return 0.0, []

        try:
            img1 = Image.open(figma_path).convert("RGBA")
            img2 = Image.open(rendered_path).convert("RGBA")

            target_w = min(img1.width, img2.width)
            target_h = min(img1.height, img2.height)
            img1 = img1.resize((target_w, target_h), Image.LANCZOS)
            img2 = img2.resize((target_w, target_h), Image.LANCZOS)

            diff_img = Image.new("RGBA", (target_w, target_h))
            num_diff = _pm(img1, img2, diff_img, threshold=0.1)

            total_pixels = target_w * target_h
            match_ratio = 1.0 - (num_diff / total_pixels)
            score = max(0.0, min(1.0, match_ratio))
            logger.info(f"[VISION] pixelmatch: {num_diff}/{total_pixels} diff pixels → score={score:.2%}")
            return score, []
        except Exception as e:
            logger.warning(f"[VISION] pixelmatch failed: {e} — vision score = 0")
            return 0.0, []

    def _encode_image(self, image_path: str, max_width: int = 1024) -> str:
        """Load image, resize to max_width preserving aspect ratio, return base64 PNG.

        Keeping audit images at ≤1024px wide avoids unnecessary token spend
        while preserving enough detail for colour/spacing comparison.
        """
        img = Image.open(image_path).convert("RGB")
        if img.width > max_width:
            ratio = max_width / img.width
            img = img.resize((max_width, int(img.height * ratio)), Image.Resampling.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    def _build_vision_prompt(self, figma_metadata: Optional[Dict]) -> str:
        """Build the prompt for vision model analysis"""
        return """Compare these two UI screenshots. Rate visual similarity 0-100.

Scoring guide:
90-100: Nearly identical layout, colors, and content
80-89: Same layout structure, minor spacing/color differences
70-79: Recognizably the same design, some elements differ in size or position
60-69: Similar structure but noticeable differences in layout or content
50-59: Same general concept but significant layout differences
Below 50: Very different designs

Focus on: presence of all UI elements (sidebar, cards, buttons, text), correct layout structure (sidebar left, content right, grid of cards), correct colors and images. Do NOT heavily penalize minor spacing differences or font rendering differences.

Return ONLY a JSON object: {"score": NUMBER, "issues": ["issue1", "issue2"]}"""

    def _parse_vision_response(self, content) -> Dict:
        """Parse the vision model's response — accepts str or pre-parsed dict/number."""
        try:
            # If already a dict (pre-parsed by _anthropic_vision_analysis), use directly
            if isinstance(content, dict):
                data = content
            elif isinstance(content, (int, float)):
                data = {"score": content, "issues": []}
            else:
                # String: try to extract JSON from markdown code blocks
                if "```json" in content:
                    json_str = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    json_str = content.split("```")[1].split("```")[0].strip()
                else:
                    json_str = content.strip()

                data = json.loads(json_str)

            # Guard against bare number/string from json.loads
            if not isinstance(data, dict):
                raw_score = float(data) if str(data).replace('.', '', 1).isdigit() else 50.0
                score = raw_score / 100.0 if raw_score > 1.0 else raw_score
                return {"score": max(0.0, min(1.0, score)), "layout_score": 0.0,
                        "color_score": 0.0, "typography_score": 0.0, "issues": []}

            # Support both new format {"score": N, "issues": [...]}
            # and old format {"overall_score": N, "critical_issues": [...]}
            raw_score = data.get("score", data.get("overall_score", 0.0))
            # New prompt returns 0-100; old prompt returned 0.0-1.0 — normalise
            score = raw_score / 100.0 if raw_score > 1.0 else raw_score

            issues = (
                data.get("issues", [])
                + data.get("critical_issues", [])
                + data.get("minor_issues", [])
            )

            return {
                "score": score,
                "layout_score": data.get("layout_score", 0.0),
                "color_score": data.get("color_score", 0.0),
                "typography_score": data.get("typography_score", 0.0),
                "issues": issues
            }

        except json.JSONDecodeError as e:
            print(f"   ⚠️  Failed to parse vision response as JSON: {e}")
            print(f"   Raw response: {content[:200]}...")
            # Try to salvage a numeric score from plain text like "score: 75" or "75/100"
            m = re.search(r'\b(\d{1,3})\b', content)
            score = int(m.group(1)) / 100.0 if m else 0.5
            score = max(0.0, min(1.0, score))  # clamp to [0, 1]
            return {
                "score": score,
                "issues": [],
                "raw_response": content,
                "parse_error": str(e)
            }

    def _calculate_overall_score(
        self,
        structural: float,
        pixel: float,
        vision: float
    ) -> float:
        """
        Calculate weighted average score
        Vision model gets highest weight as it understands semantic differences
        """
        # If no vision score, weight structural and pixel equally
        if vision == 0.0:
            return (structural * 0.5 + pixel * 0.5)

        # With vision, give it priority
        return (structural * 0.25 + pixel * 0.25 + vision * 0.50)

    def _generate_recommendations(
        self,
        structural: float,
        pixel: float,
        vision: float,
        issues: List[Dict]
    ) -> List[str]:
        """Generate actionable recommendations for improvement"""
        recommendations = []

        # Prioritize based on scores
        if structural < 0.90:
            recommendations.append(
                "Layout structure differs significantly. Check component hierarchy and positioning."
            )

        if pixel < 0.90:
            recommendations.append(
                "Pixel-level differences detected. Review colors, borders, and shadows."
            )

        if vision < 0.90:
            recommendations.append(
                "Semantic design differences found. Review typography, spacing, and visual hierarchy."
            )

        # Add specific issue-based recommendations
        critical_issues = [
            i for i in issues
            if isinstance(i, dict) and i.get("severity") == "critical"
        ]
        if critical_issues:
            recommendations.append(
                f"🚨 {len(critical_issues)} critical issues must be fixed before deployment."
            )

        return recommendations

    def generate_diff_image(
        self,
        figma_path: str,
        rendered_path: str,
        output_path: str
    ) -> str:
        """
        Generate a visual diff image highlighting differences
        """
        figma_img = Image.open(figma_path).convert("RGB")
        rendered_img = Image.open(rendered_path).convert("RGB")

        # Resize if needed
        if figma_img.size != rendered_img.size:
            rendered_img = rendered_img.resize(figma_img.size, Image.Resampling.LANCZOS)

        # Calculate difference
        diff_img = ImageChops.difference(figma_img, rendered_img)

        # Enhance the difference for visibility
        diff_img = diff_img.point(lambda p: p * 5)  # Amplify differences

        # Save
        diff_img.save(output_path)
        print(f"   💾 Diff image saved: {output_path}")

        return output_path


# Standalone test function
def test_auditor():
    """Test the visual auditor with sample images"""
    print("🧪 Testing Visual Auditor\n")

    auditor = VisualAuditor(threshold=0.95)

    # Create dummy test images
    test_dir = Path("test_audit")
    test_dir.mkdir(exist_ok=True)

    # Create test images (red and slightly different red)
    img1 = Image.new("RGB", (800, 600), color=(255, 0, 0))
    img2 = Image.new("RGB", (800, 600), color=(250, 5, 5))  # Slightly different

    img1_path = test_dir / "original.png"
    img2_path = test_dir / "generated.png"

    img1.save(img1_path)
    img2.save(img2_path)

    result = auditor.audit(str(img1_path), str(img2_path))

    print("\n📊 Test Results:")
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    test_auditor()
