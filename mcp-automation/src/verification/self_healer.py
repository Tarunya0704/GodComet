"""
Self-Healer - Automatically fixes visual discrepancies by regenerating code with constraints
Takes Visual Auditor's diff report and creates targeted fixes
"""

import json
from typing import Dict, List, Optional
from pathlib import Path


class SelfHealer:
    """
    Analyzes Visual Auditor results and generates corrected code
    Uses constrained prompts to fix specific issues
    """

    def __init__(self, max_iterations: int = 3):
        """
        Initialize Self-Healer

        Args:
            max_iterations: Maximum number of healing attempts
        """
        self.max_iterations = max_iterations
        self.iteration_count = 0

    def generate_healing_prompt(
        self,
        original_prompt: str,
        audit_result: Dict,
        figma_metadata: Optional[Dict] = None
    ) -> str:
        """
        Generate an enhanced prompt with specific corrections

        Args:
            original_prompt: The original Figma-to-code prompt
            audit_result: Result from VisualAuditor.audit()
            figma_metadata: Original Figma design metadata

        Returns:
            Enhanced prompt with correction instructions
        """
        self.iteration_count += 1

        issues = audit_result.get("issues", [])
        score = audit_result.get("score", 0.0)

        # Separate critical and minor issues
        critical = [i for i in issues if i.get("severity") == "critical"]
        minor = [i for i in issues if i.get("severity") == "minor"]

        # Build the correction section
        corrections = self._build_corrections_text(critical, minor)

        healing_prompt = f"""
{original_prompt}

═══════════════════════════════════════════════════════════════
🔄 SELF-HEALING ITERATION {self.iteration_count}/{self.max_iterations}
═══════════════════════════════════════════════════════════════

⚠️  PREVIOUS GENERATION ISSUES:
Previous visual accuracy score: {score:.1%} (target: 95%+)

{corrections}

🎯 CRITICAL REQUIREMENTS:
1. You MUST fix ALL critical issues listed above
2. Match the EXACT values specified (colors, spacing, fonts)
3. Maintain the overall layout structure from the Figma design
4. Do NOT introduce new issues while fixing existing ones
5. Pay special attention to:
   - Color precision (exact hex values)
   - Spacing accuracy (exact px/rem values)
   - Typography matching (font family, size, weight)
   - Element positioning and alignment

🔍 VERIFICATION CHECKLIST:
Before returning code, verify:
□ All critical color mismatches are corrected
□ All spacing/padding values match specifications
□ Typography (font-family, size, weight) is accurate
□ No elements are missing or misplaced
□ Layout structure matches Figma exactly

Re-generate the code with these corrections applied.
"""

        return healing_prompt

    def _build_corrections_text(
        self,
        critical_issues: List[Dict],
        minor_issues: List[Dict]
    ) -> str:
        """Build formatted correction instructions"""
        text = ""

        # Critical issues
        if critical_issues:
            text += "🚨 CRITICAL ISSUES (MUST FIX):\n\n"
            for i, issue in enumerate(critical_issues, 1):
                text += self._format_issue(i, issue)
                text += "\n"

        # Minor issues
        if minor_issues:
            text += "\n⚠️  MINOR ISSUES (Should Fix):\n\n"
            for i, issue in enumerate(minor_issues, 1):
                text += self._format_issue(i, issue)
                text += "\n"

        if not critical_issues and not minor_issues:
            text += "No specific issues detected, but overall score is below threshold.\n"
            text += "Review the generated code and improve visual accuracy.\n"

        return text

    def _format_issue(self, index: int, issue: Dict) -> str:
        """Format a single issue for the prompt"""
        issue_type = issue.get("type", "unknown")
        element = issue.get("element", "unknown element")
        expected = issue.get("expected", "N/A")
        actual = issue.get("actual", "N/A")
        fix = issue.get("fix", "")

        formatted = f"{index}. {issue_type.upper().replace('_', ' ')}\n"
        formatted += f"   Element: {element}\n"
        formatted += f"   Expected: {expected}\n"
        formatted += f"   Actual: {actual}\n"

        if fix:
            formatted += f"   Fix: {fix}\n"

        return formatted

    def should_continue_healing(self, audit_result: Dict) -> bool:
        """
        Determine if another healing iteration is needed

        Returns:
            True if should continue, False if should stop
        """
        # Stop if passed threshold
        if audit_result.get("passed", False):
            return False

        # Stop if max iterations reached
        if self.iteration_count >= self.max_iterations:
            return False

        # Continue if there are fixable issues
        return True

    def analyze_improvement(
        self,
        previous_score: float,
        current_score: float
    ) -> Dict:
        """
        Analyze if the healing iteration improved the score

        Returns:
            {
                "improved": True/False,
                "delta": 0.05,
                "recommendation": "continue" | "stop" | "human_review"
            }
        """
        delta = current_score - previous_score

        if delta > 0.02:  # Significant improvement
            return {
                "improved": True,
                "delta": delta,
                "recommendation": "continue"
            }
        elif delta > 0:  # Minor improvement
            return {
                "improved": True,
                "delta": delta,
                "recommendation": "continue"
            }
        elif delta < -0.01:  # Got worse
            return {
                "improved": False,
                "delta": delta,
                "recommendation": "stop"  # Stop if healing makes it worse
            }
        else:  # No change
            return {
                "improved": False,
                "delta": delta,
                "recommendation": "human_review"  # Stuck, need human
            }

    def generate_css_patch(self, issues: List[Dict]) -> str:
        """
        Generate a targeted CSS patch for common issues
        This can be applied quickly without full regeneration

        Returns:
            CSS string with corrections
        """
        css_patches = []

        for issue in issues:
            issue_type = issue.get("type", "")
            element = issue.get("element", "")
            expected = issue.get("expected", "")

            if issue_type == "color_mismatch":
                selector = self._element_to_selector(element)
                if "background" in element.lower():
                    css_patches.append(f"{selector} {{ background-color: {expected} !important; }}")
                else:
                    css_patches.append(f"{selector} {{ color: {expected} !important; }}")

            elif issue_type == "spacing":
                selector = self._element_to_selector(element)
                if "padding" in element.lower():
                    css_patches.append(f"{selector} {{ padding: {expected} !important; }}")
                elif "margin" in element.lower():
                    css_patches.append(f"{selector} {{ margin: {expected} !important; }}")

            elif issue_type == "typography":
                selector = self._element_to_selector(element)
                css_patches.append(f"{selector} {{ font-size: {expected} !important; }}")

        if css_patches:
            return "/* Self-Healer CSS Patch */\n" + "\n".join(css_patches)
        else:
            return ""

    def _element_to_selector(self, element_description: str) -> str:
        """
        Convert element description to CSS selector
        Example: "primary button" -> ".primary-button"
        """
        # Simple heuristic conversion
        selector = element_description.lower()
        selector = selector.replace(" ", "-")

        # If it looks like a class or ID, return as-is
        if selector.startswith(".") or selector.startswith("#"):
            return selector

        # Otherwise, assume it's a class
        return f".{selector}"

    def reset_iteration_count(self):
        """Reset iteration counter for a new healing session"""
        self.iteration_count = 0

    def create_healing_report(
        self,
        original_score: float,
        final_score: float,
        iterations: int,
        final_audit: Dict
    ) -> Dict:
        """
        Create a comprehensive report of the healing process

        Returns:
            {
                "success": True/False,
                "original_score": 0.85,
                "final_score": 0.97,
                "improvement": 0.12,
                "iterations": 2,
                "remaining_issues": [...],
                "recommendation": "deploy" | "needs_review"
            }
        """
        improvement = final_score - original_score
        success = final_audit.get("passed", False)

        recommendation = "deploy" if success else "needs_review"

        return {
            "success": success,
            "original_score": original_score,
            "final_score": final_score,
            "improvement": improvement,
            "improvement_percentage": (improvement / original_score) * 100 if original_score > 0 else 0,
            "iterations": iterations,
            "remaining_issues": final_audit.get("issues", []),
            "recommendation": recommendation,
            "summary": self._generate_summary(success, improvement, iterations)
        }

    def _generate_summary(
        self,
        success: bool,
        improvement: float,
        iterations: int
    ) -> str:
        """Generate human-readable summary"""
        if success:
            return f"✅ Self-healing successful! Improved by {improvement:.1%} in {iterations} iteration(s). Ready to deploy."
        elif improvement > 0:
            return f"⚠️  Partial improvement (+{improvement:.1%}) but still below threshold after {iterations} iterations. Human review recommended."
        else:
            return f"❌ Self-healing failed to improve score after {iterations} iterations. Manual intervention required."


# Standalone test
def test_self_healer():
    """Test the self-healer with mock audit results"""
    print("🧪 Testing Self-Healer\n")

    healer = SelfHealer(max_iterations=3)

    # Mock audit result
    mock_audit = {
        "score": 0.87,
        "passed": False,
        "issues": [
            {
                "type": "color_mismatch",
                "element": "primary button",
                "expected": "#3B82F6",
                "actual": "#60A5FA",
                "severity": "critical",
                "fix": "Change button background to #3B82F6"
            },
            {
                "type": "spacing",
                "element": "header padding",
                "expected": "24px",
                "actual": "20px",
                "severity": "minor"
            }
        ]
    }

    original_prompt = "Generate a React component based on this Figma design."

    # Generate healing prompt
    healing_prompt = healer.generate_healing_prompt(
        original_prompt,
        mock_audit
    )

    print("📝 Generated Healing Prompt:")
    print("=" * 80)
    print(healing_prompt)
    print("=" * 80)

    # Test CSS patch generation
    css_patch = healer.generate_css_patch(mock_audit["issues"])
    print("\n🎨 Generated CSS Patch:")
    print(css_patch)

    # Test improvement analysis
    improvement = healer.analyze_improvement(0.87, 0.92)
    print(f"\n📊 Improvement Analysis:")
    print(json.dumps(improvement, indent=2))


if __name__ == "__main__":
    test_self_healer()
