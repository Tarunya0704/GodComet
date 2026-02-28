"""
Visual Auditor - Compare Figma designs to rendered code using Vision LLMs
This is the core "moat" that guarantees design fidelity
"""

import os
import json
import base64
from typing import Dict, List, Tuple, Optional
from pathlib import Path
from PIL import Image, ImageChops
import numpy as np
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
        use_anthropic: bool = False,
        groq_model: str = "meta-llama/llama-4-scout-17b-16e-instruct",
        openai_model: str = "gpt-4o-mini",
        anthropic_model: str = "claude-3-5-sonnet-20241022"
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
        """Load images and ensure they're the same size"""
        figma_img = Image.open(figma_path).convert("RGB")
        rendered_img = Image.open(rendered_path).convert("RGB")

        # Resize rendered to match Figma dimensions
        if figma_img.size != rendered_img.size:
            print(f"   ⚙️  Resizing: {rendered_img.size} → {figma_img.size}")
            rendered_img = rendered_img.resize(figma_img.size, Image.Resampling.LANCZOS)

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
        """Use Vision LLM to analyze semantic differences"""

        # Try Groq first (FREE and FAST!)
        if self.groq_client:
            return self._groq_vision_analysis(figma_path, rendered_path, figma_metadata)

        # Fallback to OpenAI
        elif self.openai_client:
            return self._openai_vision_analysis(figma_path, rendered_path, figma_metadata)

        # Fallback to Anthropic
        elif self.anthropic_client:
            return self._anthropic_vision_analysis(figma_path, rendered_path, figma_metadata)

        # No vision models available
        else:
            return {
                "score": 0.0,
                "issues": [],
                "note": "No vision models available"
            }

    def _groq_vision_analysis(
        self,
        figma_path: str,
        rendered_path: str,
        figma_metadata: Optional[Dict]
    ) -> Dict:
        """Use Groq Llama 3.2 Vision for analysis"""
        try:
            # Encode images to base64
            figma_b64 = self._encode_image(figma_path)
            rendered_b64 = self._encode_image(rendered_path)

            # Build prompt
            prompt = self._build_vision_prompt(figma_metadata)

            # Groq Vision API call
            response = self.groq_client.chat.completions.create(
                model=self.groq_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{figma_b64}"
                                }
                            },
                            {
                                "type": "text",
                                "text": "Generated Website (Candidate):"
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{rendered_b64}"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=2000,
                temperature=0.1  # Low temperature for consistent analysis
            )

            content = response.choices[0].message.content
            return self._parse_vision_response(content)

        except Exception as e:
            print(f"   ⚠️  Groq vision analysis failed: {e}")
            return {"score": 0.0, "issues": [], "error": str(e)}

    def _openai_vision_analysis(
        self,
        figma_path: str,
        rendered_path: str,
        figma_metadata: Optional[Dict]
    ) -> Dict:
        """Use OpenAI GPT-4o for vision analysis"""
        try:
            # Encode images to base64
            figma_b64 = self._encode_image(figma_path)
            rendered_b64 = self._encode_image(rendered_path)

            # Build prompt
            prompt = self._build_vision_prompt(figma_metadata)

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
                                    "url": f"data:image/png;base64,{figma_b64}",
                                    "detail": "high"
                                }
                            },
                            {
                                "type": "text",
                                "text": "Generated Website (Candidate):"
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{rendered_b64}",
                                    "detail": "high"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=2000,
                temperature=0.1  # Low temperature for consistent analysis
            )

            content = response.choices[0].message.content
            return self._parse_vision_response(content)

        except Exception as e:
            print(f"   ⚠️  OpenAI vision analysis failed: {e}")
            return {"score": 0.0, "issues": [], "error": str(e)}

    def _anthropic_vision_analysis(
        self,
        figma_path: str,
        rendered_path: str,
        figma_metadata: Optional[Dict]
    ) -> Dict:
        """Use Anthropic Claude for vision analysis"""
        try:
            # Encode images to base64
            figma_b64 = self._encode_image(figma_path)
            rendered_b64 = self._encode_image(rendered_path)

            prompt = self._build_vision_prompt(figma_metadata)

            response = self.anthropic_client.messages.create(
                model=self.anthropic_model,
                max_tokens=2000,
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
                                    "data": figma_b64
                                }
                            },
                            {
                                "type": "text",
                                "text": "Generated Website (Candidate):"
                            },
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": rendered_b64
                                }
                            }
                        ]
                    }
                ]
            )

            content = response.content[0].text
            return self._parse_vision_response(content)

        except Exception as e:
            print(f"   ⚠️  Claude vision analysis failed: {e}")
            return {"score": 0.0, "issues": [], "error": str(e)}

    def _encode_image(self, image_path: str) -> str:
        """Encode image to base64 string"""
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def _build_vision_prompt(self, figma_metadata: Optional[Dict]) -> str:
        """Build the prompt for vision model analysis"""
        base_prompt = """You are a UI/UX expert comparing two designs:
1. **Original Figma Design** (reference/expected)
2. **Generated Website** (candidate/actual)

Analyze these images and identify ALL differences:

**Critical Issues** (must fix):
- Layout differences (alignment, spacing, positioning)
- Color mismatches (even slight variations)
- Typography errors (font family, size, weight, line-height)
- Missing elements or extra elements
- Border/shadow differences
- Image/icon discrepancies

**Minor Issues** (nice to fix):
- Subtle spacing variations (<5px)
- Anti-aliasing differences
- Minor color shades (#3B82F6 vs #3B82F7)

Return your analysis as JSON:
```json
{
  "layout_score": 0.95,
  "color_score": 0.98,
  "typography_score": 0.96,
  "overall_score": 0.96,
  "critical_issues": [
    {
      "type": "color_mismatch",
      "element": "primary button",
      "expected": "#3B82F6",
      "actual": "#60A5FA",
      "severity": "critical",
      "fix": "Change button background to #3B82F6"
    }
  ],
  "minor_issues": [
    {
      "type": "spacing",
      "element": "header padding",
      "expected": "24px",
      "actual": "20px",
      "severity": "minor"
    }
  ]
}
```

**Original Figma Design (Reference):**
"""

        # Add figma metadata if available
        if figma_metadata:
            base_prompt += f"\n\nDesign Context:\n{json.dumps(figma_metadata, indent=2)}\n"

        return base_prompt

    def _parse_vision_response(self, content: str) -> Dict:
        """Parse the vision model's JSON response"""
        try:
            # Try to extract JSON from markdown code blocks
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0].strip()
            else:
                json_str = content.strip()

            data = json.loads(json_str)

            # Combine critical and minor issues
            issues = data.get("critical_issues", []) + data.get("minor_issues", [])

            return {
                "score": data.get("overall_score", 0.0),
                "layout_score": data.get("layout_score", 0.0),
                "color_score": data.get("color_score", 0.0),
                "typography_score": data.get("typography_score", 0.0),
                "issues": issues
            }

        except json.JSONDecodeError as e:
            print(f"   ⚠️  Failed to parse vision response as JSON: {e}")
            print(f"   Raw response: {content[:200]}...")
            return {
                "score": 0.0,
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
        critical_issues = [i for i in issues if i.get("severity") == "critical"]
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
