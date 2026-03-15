"""
Self-Healer - Automatically fixes visual discrepancies by regenerating code with constraints
Takes Visual Auditor's diff report and creates targeted fixes
"""

import io
import json
import os
import re
import base64
from typing import Dict, List, Optional
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent.parent / ".env")

try:
    from anthropic import Anthropic as _Anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

try:
    from groq import Groq as _Groq
    _GROQ_AVAILABLE = True
except ImportError:
    _GROQ_AVAILABLE = False


class SelfHealer:
    """
    Analyzes Visual Auditor results and generates corrected code.
    Uses constrained prompts to fix specific issues.
    `fix_with_vision` sends both images to GPT-4o for direct code repair.
    """

    def __init__(self, max_iterations: int = 3):
        """
        Initialize Self-Healer

        Args:
            max_iterations: Maximum number of healing attempts
        """
        self.max_iterations = max_iterations
        self.iteration_count = 0

        # Vision clients — used by fix_with_vision()
        self.anthropic_client = None
        self.groq_client = None
        self.groq_model = "meta-llama/llama-4-scout-17b-16e-instruct"
        self.claude_model = "claude-sonnet-4-20250514"

        if _ANTHROPIC_AVAILABLE:
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if api_key:
                self.anthropic_client = _Anthropic(api_key=api_key)

        if _GROQ_AVAILABLE:
            api_key = os.getenv("GROQ_API_KEY")
            if api_key:
                self.groq_client = _Groq(api_key=api_key)

    # ── Vision helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _encode_image_for_vision(image_path: str, max_width: int = 1024) -> str:
        """Load image, resize to max_width preserving aspect ratio, return base64 PNG."""
        from PIL import Image

        img = Image.open(image_path).convert("RGB")
        if img.width > max_width:
            ratio = max_width / img.width
            img = img.resize((max_width, int(img.height * ratio)), Image.Resampling.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    def fix_with_vision(
        self,
        current_code: str,
        figma_path: str,
        rendered_path: str,
        issues: List[Dict],
        component_name: str = "Component",
    ) -> Optional[str]:
        """Send target design + rendered screenshot + audit issues to GPT-4o vision.

        Returns fixed TSX code, or None if no LLM is available / call fails.

        Args:
            current_code:   The TSX code that produced the rendered screenshot.
            figma_path:     Path to the original Figma design screenshot.
            rendered_path:  Path to the screenshot of the current rendered output.
            issues:         Issue list from VisualAuditor.audit()["issues"].
            component_name: Used only for logging.
        """
        if not self.anthropic_client and not self.groq_client:
            print("⚠️  SelfHealer.fix_with_vision: no LLM client available")
            return None

        if not Path(figma_path).exists() or not Path(rendered_path).exists():
            print(f"⚠️  SelfHealer.fix_with_vision: image not found — "
                  f"figma={figma_path} rendered={rendered_path}")
            return None

        # Format issues into a readable list
        issue_lines: List[str] = []
        for idx, issue in enumerate(issues, 1):
            severity = issue.get("severity", "")
            itype    = issue.get("type", "")
            element  = issue.get("element", "")
            expected = issue.get("expected", "")
            actual   = issue.get("actual", "")
            fix      = issue.get("fix", "")

            line = f"{idx}. [{severity.upper()}] {itype}: {element}"
            if expected and actual:
                line += f" (expected {expected}, got {actual})"
            if fix:
                line += f" → {fix}"
            issue_lines.append(line)

        issues_text = (
            "\n".join(issue_lines)
            if issue_lines
            else "General visual mismatch — compare both images carefully."
        )

        # Encode both images at ≤1024px
        figma_b64    = self._encode_image_for_vision(figma_path)
        rendered_b64 = self._encode_image_for_vision(rendered_path)

        user_prompt = (
            f"Issues found by visual audit:\n{issues_text}\n\n"
            "Fix the code to close the gap between the two images. "
            "Rules:\n"
            "- Use arbitrary Tailwind values for exact measurements "
            "(gap-[13px], text-[#2D3748], w-[280px])\n"
            "- Do not change component structure or add/remove elements\n"
            "- Fix: spacing, padding, margins, colors, font sizes, alignment, "
            "border radius, shadows\n"
            "- Return ONLY the complete fixed code, no explanation\n\n"
            f"Current code:\n{current_code}"
        )

        system_text = (
            "You are a pixel-perfect frontend developer. "
            "Output ONLY raw TSX — no markdown fences, no explanation."
        )
        # Anthropic format (primary)
        anthropic_messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Here is the target design:"},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": figma_b64}},
                    {"type": "text", "text": "Here is what your code currently renders:"},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": rendered_b64}},
                    {"type": "text", "text": user_prompt},
                ],
            },
        ]
        # Groq fallback format (text-only — no vision)
        groq_messages = [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_prompt},
        ]

        # If component is large, chunk it and heal only the affected sections
        _CHUNK_THRESHOLD = 10_000
        _CHUNK_SIZE = 8_000

        if len(current_code) > _CHUNK_THRESHOLD:
            print(
                f"🔧 SelfHealer: {component_name} is {len(current_code)} chars — "
                f"using chunk-based healing"
            )
            return self._fix_with_vision_chunked(
                current_code=current_code,
                figma_path=figma_path,
                rendered_path=rendered_path,
                issues=issues,
                component_name=component_name,
                chunk_size=_CHUNK_SIZE,
                figma_b64=figma_b64,
                rendered_b64=rendered_b64,
                issues_text=issues_text,
            )

        try:
            if self.anthropic_client:
                print(f"🔧 SelfHealer: calling Claude vision ({self.claude_model}) for {component_name}")
                response = self.anthropic_client.messages.create(
                    model=self.claude_model,
                    system=system_text,
                    messages=anthropic_messages,
                    max_tokens=8192,
                )
                code = response.content[0].text
            else:
                print(f"🔧 SelfHealer: calling Groq (text-only fallback) for {component_name}")
                response = self.groq_client.chat.completions.create(
                    model=self.groq_model,
                    messages=groq_messages,
                    temperature=0.1,
                    max_tokens=8192,
                )
                code = response.choices[0].message.content

            # Strip markdown fences if model wrapped output
            if "```" in code:
                m = re.search(
                    r'```(?:tsx|jsx|typescript|javascript)?\n(.*?)```',
                    code,
                    re.DOTALL,
                )
                if m:
                    code = m.group(1).strip()

            # Sanity checks — export default must be present, output must not be truncated.
            # NOTE: brace-balance check removed — TSX has legitimately unequal { } counts
            # inside string literals and JSX attributes.
            if "export default" not in code:
                print(
                    f"⚠️  SelfHealer.fix_with_vision: output missing export default — discarding. "
                    f"Last 200: {code[-200:]!r}"
                )
                return None
            _last = code.rstrip()[-1] if code.rstrip() else ""
            if _last not in ("}", ";"):
                print(
                    f"⚠️  SelfHealer.fix_with_vision: output truncated (last char={_last!r}) — discarding. "
                    f"Last 200: {code[-200:]!r}"
                )
                return None

            print(f"✅ SelfHealer: vision fix produced {len(code)} chars for {component_name}")
            return code

        except Exception as e:
            print(f"⚠️  SelfHealer.fix_with_vision failed: {e}")
            return None

    def _fix_with_vision_chunked(
        self,
        current_code: str,
        figma_path: str,
        rendered_path: str,
        issues: List[Dict],
        component_name: str,
        chunk_size: int,
        figma_b64: str,
        rendered_b64: str,
        issues_text: str,
    ) -> Optional[str]:
        """Heal a large component by:
        1. Extracting the inner JSX body from 'return (...)'
        2. Splitting it into JSX FRAGMENTS (not full code chunks)
        3. Sending each fragment with explicit 'do not wrap in component' instruction
        4. Reassembling and validating

        This avoids the bug where the AI wraps each chunk in its own export default,
        producing multiple orphaned functions when concatenated.
        """
        # Step 1: extract JSX body
        extracted = self._extract_jsx_body(current_code)
        if extracted is None:
            print(f"⚠️  SelfHealer: cannot extract JSX body for {component_name} — skipping chunk heal")
            return None

        prefix, jsx_body, suffix = extracted
        fragments = self._split_jsx_fragments(jsx_body, chunk_size)
        print(
            f"🔧 SelfHealer fragment-heal: {len(fragments)} fragments, "
            f"sizes={[len(f) for f in fragments]}"
        )

        # Build keyword set from issues so we only heal relevant fragments
        issue_keywords: set = set()
        for iss in issues:
            for field in ("element", "type", "expected", "actual", "fix"):
                val = iss.get(field, "")
                if val:
                    issue_keywords.update(w for w in str(val).split() if len(w) >= 4)

        system_text = (
            "You output ONLY raw JSX fragments. "
            "Never wrap output in a function, export, or component declaration. "
            "No markdown fences, no explanation."
        )

        enhanced_fragments: List[str] = []
        for i, frag in enumerate(fragments):
            frag_lower = frag.lower()
            frag_relevant = (
                not issue_keywords
                or any(kw.lower() in frag_lower for kw in issue_keywords)
            )

            if not frag_relevant:
                print(f"  Fragment {i + 1}/{len(fragments)}: no issue keywords — keeping as-is")
                enhanced_fragments.append(frag)
                continue

            print(f"  Fragment {i + 1}/{len(fragments)}: healing ({len(frag)} chars)")

            user_prompt = (
                f"Issues found by visual audit:\n{issues_text}\n\n"
                f"This is JSX fragment {i + 1} of {len(fragments)} from component '{component_name}'.\n\n"
                "CRITICAL: This is a RAW JSX FRAGMENT — NOT a complete React component.\n"
                "DO NOT add 'export default', 'function', 'const', 'return', or any wrapper.\n\n"
                "YOUR ONLY JOB: Fix the specific issues listed above. Nothing else.\n\n"
                "STRICT RULES — read carefully:\n"
                "1. PRESERVE all existing colors, backgrounds, and values that already look correct "
                "in the rendered image. If a color or style is NOT mentioned in the issues list, "
                "DO NOT change it. When in doubt, keep the original value.\n"
                "2. Do NOT add or remove JSX elements — keep the exact same element tree.\n"
                "3. Do NOT rewrite or restructure JSX — only change className strings.\n"
                "4. Use arbitrary Tailwind values for fixes: gap-[13px], w-[280px], text-[#2D3748].\n"
                "5. Return ONLY the corrected JSX fragment — same structure as input, "
                "no markdown fences, no explanation.\n\n"
                f"JSX fragment:\n{frag}"
            )

            # Anthropic format (vision)
            frag_anthropic_msgs = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Target design:"},
                        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": figma_b64}},
                        {"type": "text", "text": "Current rendered output:"},
                        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": rendered_b64}},
                        {"type": "text", "text": user_prompt},
                    ],
                },
            ]
            # Groq fallback (text-only)
            frag_groq_msgs = [
                {"role": "system", "content": system_text},
                {"role": "user", "content": user_prompt},
            ]

            try:
                fixed = None
                if self.anthropic_client:
                    resp = self.anthropic_client.messages.create(
                        model=self.claude_model,
                        system=system_text,
                        messages=frag_anthropic_msgs,
                        max_tokens=8192,
                    )
                    fixed = resp.content[0].text
                elif self.groq_client:
                    resp = self.groq_client.chat.completions.create(
                        model=self.groq_model, messages=frag_groq_msgs, temperature=0.1, max_tokens=8192,
                    )
                    fixed = resp.choices[0].message.content

                if fixed and "```" in fixed:
                    m = re.search(r'```(?:tsx|jsx|typescript|javascript|html)?\n(.*?)```', fixed, re.DOTALL)
                    if m:
                        fixed = m.group(1)

                # Reject if AI wrapped in component anyway
                if fixed and "export default" in fixed:
                    print(f"  Fragment {i + 1}: AI wrapped output in component — keeping original")
                    enhanced_fragments.append(frag)
                elif fixed and fixed.strip():
                    enhanced_fragments.append(fixed)
                else:
                    print(f"  Fragment {i + 1}: empty response — keeping original")
                    enhanced_fragments.append(frag)
            except Exception as e:
                print(f"  Fragment {i + 1}: AI call failed ({e}) — keeping original")
                enhanced_fragments.append(frag)

        # Reassemble
        enhanced_body = "".join(enhanced_fragments)
        result = prefix + enhanced_body + suffix

        if not self._validate_assembled_tsx(result, component_name):
            print(f"⚠️  SelfHealer: fragment reassembly failed validation — discarding")
            return None

        print(f"✅ SelfHealer fragment-heal: produced {len(result)} chars for {component_name}")
        return result

    @staticmethod
    def _extract_jsx_body(code: str):
        """Extract (prefix, jsx_body, suffix) from a TSX component's return statement.
        Returns None if extraction fails.
        """
        matches = list(re.finditer(r'\breturn\s*\(', code))
        if not matches:
            return None
        m = matches[-1]
        prefix = code[:m.end()]
        rest = code[m.end():]

        depth = 1
        i = 0
        in_str = None
        while i < len(rest) and depth > 0:
            ch = rest[i]
            if in_str:
                if ch == "\\" and in_str != "`":
                    i += 2
                    continue
                if ch == in_str:
                    in_str = None
            else:
                if ch in ('"', "'", "`"):
                    in_str = ch
                elif ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
            i += 1

        if depth != 0:
            return None

        return prefix, rest[:i - 1], rest[i - 1:]

    @staticmethod
    def _split_jsx_fragments(jsx_body: str, chunk_size: int = 8_000) -> List[str]:
        """Split a JSX body string into fragments ≤ chunk_size chars at close-tag boundaries."""
        lines = jsx_body.splitlines(keepends=True)
        fragments: List[str] = []
        current: List[str] = []
        current_size = 0

        def _is_close(line: str) -> bool:
            s = line.strip()
            return (
                s.startswith("</")
                or s in (")", "};", "})", ");", "}", "/>", "")
                or s.startswith(");")
            )

        for line in lines:
            current.append(line)
            current_size += len(line)
            if current_size >= chunk_size and _is_close(line):
                fragments.append("".join(current))
                current = []
                current_size = 0

        if current:
            fragments.append("".join(current))

        if len(fragments) > 1 and len(fragments[-1]) < 300:
            fragments[-2] += fragments[-1]
            fragments.pop()

        return fragments if fragments else [jsx_body]

    @staticmethod
    def _validate_assembled_tsx(code: str, component_name: str) -> bool:
        """Sanity check assembled TSX before writing to disk.

        Checks:
          1. Exactly one 'export default'
          2. Last non-whitespace character is '}'
          3. JSX tag balance — open tags roughly equal close tags
             (allows ≤ 3 difference to tolerate self-closing & fragments)
        """
        if code.count("export default") != 1:
            print(
                f"⚠️  [VALIDATE] {component_name}: "
                f"expected 1 'export default', got {code.count('export default')}"
            )
            return False

        last = code.rstrip()[-1] if code.rstrip() else ""
        if last != "}":
            print(f"⚠️  [VALIDATE] {component_name}: last char={last!r}, expected '}}'")
            return False

        # JSX tag balance: count <Tag ...> opens (not self-closing) vs </Tag> closes.
        # We strip string literals first so false matches inside attribute strings don't skew counts.
        stripped = re.sub(r'"[^"]*"|\'[^\']*\'|`[^`]*`', '""', code)
        # All opening-like tags: <Tag> or <Tag ...>
        all_open   = len(re.findall(r'<[A-Za-z][A-Za-z0-9.]*(?:\s[^>]*)?>', stripped))
        # Self-closing tags: <Tag /> or <Tag.../>  — counted in all_open but have no close tag
        self_close = len(re.findall(r'<[A-Za-z][A-Za-z0-9.]*(?:\s[^>]*)?/>', stripped))
        open_tags  = all_open - self_close  # real opening tags that need a closing tag
        close_tags = len(re.findall(r'</[A-Za-z]', stripped))
        diff = abs(open_tags - close_tags)
        total_tags = open_tags + close_tags + self_close
        threshold  = max(5, int(total_tags * 0.03))
        print(
            f"   [VALIDATE] {component_name}: open={open_tags} "
            f"(self-closing={self_close}), close={close_tags}, "
            f"adjusted_diff={diff}, threshold={threshold}"
        )
        if diff > threshold:
            print(
                f"⚠️  [VALIDATE] {component_name}: JSX tag imbalance "
                f"(open={open_tags}, close={close_tags}, diff={diff} > threshold={threshold})"
            )
            return False

        return True

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
