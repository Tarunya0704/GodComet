# Visual Auditor Architecture - The VC Moat

## Executive Summary
This document outlines the **Closed-Loop Verification System** that differentiates GodComet from standard AI coding assistants (Cursor, Copilot, Bolt.new). Our moat is **guaranteed design fidelity** through autonomous visual verification and self-healing.

---

## 1. The Problem with Current Tools

| Tool | Limitation |
|------|-----------|
| **Cursor/Copilot** | Generate code blindly - no verification it looks correct |
| **Bolt.new** | One-shot generation - no feedback loop |
| **v0.dev** | Manual iteration required |
| **Lovable** | Human reviews for accuracy |

**GodComet's Advantage:** Autonomous verification that guarantees 95%+ visual accuracy before deployment.

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    GODCOMET CLOSED-LOOP SYSTEM                   │
└─────────────────────────────────────────────────────────────────┘

   USER INPUT                  EXTRACTION                CODE GENERATION
┌──────────────┐           ┌──────────────┐           ┌──────────────┐
│  Figma URL   │──────────▶│ Figma API    │──────────▶│ AI Coder     │
│  or Hotkey   │           │ + Context    │           │ (Groq/Claude)│
└──────────────┘           │ Extraction   │           └──────┬───────┘
                           └──────────────┘                  │
                                                             │
                                                             ▼
   VERIFICATION              RENDERING                 DEPLOYMENT
┌──────────────┐           ┌──────────────┐           ┌──────────────┐
│ Visual       │◀──────────│ Playwright   │◀──────────│ Generated    │
│ Auditor      │           │ Headless     │           │ React Code   │
│ (Vision LLM) │           │ Browser      │           └──────────────┘
└──────┬───────┘           └──────────────┘
       │                          │
       │   ┌──────────────────────┘
       │   │  Screenshot
       │   │  + DOM Tree
       ▼   ▼
┌────────────────┐
│  Comparison    │
│  Engine        │
│  • Layout Δ    │
│  • Color Δ     │
│  • Typography Δ│
│  • Spacing Δ   │
└────────┬───────┘
         │
         ▼
   ┌─────────────┐
   │ Score: 97%  │───YES──▶ Deploy to Vercel
   │ Threshold?  │
   └─────┬───────┘
         │ NO (< 95%)
         ▼
   ┌─────────────┐
   │ Self-Heal   │
   │ Generator   │──────┐
   └─────────────┘      │
                        │
   ┌────────────────────┘
   │  Diff Report JSON
   │  { "issues": [
   │    {"type": "color", "expected": "#FF0000", "actual": "#FF0033"},
   │    {"type": "spacing", "element": ".header", "expected": "24px", "actual": "20px"}
   │  ]}
   │
   └────────────▶ AI Coder (Re-generate with constraints)
                      │
                      └──────────▶ Loop until Score ≥ 95%
```

---

## 3. Core Components

### A. **Visual Auditor Engine** (`visual_auditor.py`)

**Purpose:** Compare Figma design screenshots to Playwright-rendered code.

**Tech Stack:**
- **Vision Model:** GPT-4o-mini (fast, accurate) or Claude 3.5 Sonnet (best for layout)
- **Image Processing:** Pillow (PIL) for preprocessing
- **Similarity Metrics:** SSIM (Structural Similarity Index), Pixel-wise diff

**Algorithm:**
```python
def audit_design_fidelity(figma_screenshot, playwright_screenshot, figma_metadata):
    """
    Returns: {
        "score": 0.97,  # 97% match
        "issues": [
            {"type": "color_mismatch", "element": "button", "expected": "#3B82F6", "actual": "#3B82F7"},
            {"type": "spacing_error", "element": ".container", "expected": "padding: 24px", "actual": "padding: 20px"}
        ],
        "passed": True  # If score >= 0.95
    }
    """

    # Step 1: Preprocess images (resize, normalize)
    # Step 2: Structural comparison (SSIM)
    # Step 3: Vision LLM analysis (GPT-4o or Claude)
    # Step 4: Generate diff report
    # Step 5: Return actionable feedback
```

**Vision Prompt Template:**
```
You are a UI/UX expert comparing two designs:
1. Original Figma Design (reference)
2. Generated Website (candidate)

Analyze these images and identify:
- Layout differences (alignment, spacing, sizing)
- Color mismatches (hex values)
- Typography errors (font, size, weight)
- Missing elements or extra elements

Return JSON:
{
  "layout_score": 0.95,
  "color_score": 0.98,
  "typography_score": 0.96,
  "overall_score": 0.96,
  "critical_issues": [...],
  "minor_issues": [...]
}
```

---

### B. **Playwright Rendering Pipeline** (`render_engine.py`)

**Purpose:** Render generated code in a headless browser and capture screenshots.

**Features:**
- Viewport matching (same dimensions as Figma frame)
- Wait for fonts/images to load
- Disable animations (for consistent screenshots)
- Capture DOM tree + accessibility tree

**Code Flow:**
```python
async def render_generated_code(code_dir, viewport_size):
    browser = await playwright.chromium.launch()
    page = await browser.new_page(viewport=viewport_size)

    # Serve the code locally
    server = start_dev_server(code_dir)
    await page.goto(f"http://localhost:{server.port}")

    # Wait for complete render
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(1000)  # Extra buffer for fonts

    # Capture screenshot + DOM
    screenshot = await page.screenshot(full_page=True)
    dom_tree = await page.content()

    await browser.close()
    return screenshot, dom_tree
```

---

### C. **Self-Healing Generator** (`self_healer.py`)

**Purpose:** Take the Visual Auditor's diff report and re-generate code with constraints.

**Strategy:**
- Parse the diff JSON
- Extract specific CSS/component issues
- Append constraints to the AI prompt
- Limit to 3 iterations (prevent infinite loops)

**Enhanced Prompt Template:**
```python
def generate_healing_prompt(original_prompt, diff_report):
    return f"""
{original_prompt}

CRITICAL CORRECTIONS REQUIRED:
The previous generation had these issues:
{json.dumps(diff_report['issues'], indent=2)}

You MUST fix these specific problems:
1. Button color must be EXACTLY #{diff_report['issues'][0]['expected']}
2. Container padding must be EXACTLY {diff_report['issues'][1]['expected']}

Re-generate the code with these exact specifications.
"""
```

---

### D. **Confidence Scoring System**

**Metrics:**
```python
def calculate_confidence_score(figma_img, rendered_img, dom_tree):
    # Structural Similarity (0-1)
    ssim_score = compare_ssim(figma_img, rendered_img)

    # Pixel-wise difference (0-1)
    pixel_diff = 1 - (np.sum(np.abs(figma_img - rendered_img)) / figma_img.size)

    # Vision LLM semantic score (0-1)
    vision_score = vision_model.compare(figma_img, rendered_img)

    # Weighted average
    confidence = (ssim_score * 0.3 + pixel_diff * 0.3 + vision_score * 0.4)

    return confidence
```

**Thresholds:**
- `>= 0.95`: Auto-deploy (excellent match)
- `0.85 - 0.94`: Self-heal (good but needs refinement)
- `< 0.85`: Human review (significant issues)

---

## 4. Integration with Existing Pipeline

### Current Flow (Figma → Code)
```python
# In: mcp-automation/src/tools/production_figma_converter.py
def generate_website_from_figma(figma_url):
    design_data = extract_figma_design(figma_url)
    react_code = generate_react_components(design_data)
    save_to_project_dir(react_code)
    return project_path
```

### Enhanced Flow (Figma → Code → Verify → Deploy)
```python
# NEW: mcp-automation/src/tools/verified_figma_converter.py
def generate_verified_website(figma_url):
    # Step 1: Extract design
    design_data, figma_screenshot = extract_figma_with_screenshot(figma_url)

    # Step 2: Generate code
    project_path = generate_react_components(design_data)

    # Step 3: Render and verify (LOOP UP TO 3 TIMES)
    for iteration in range(3):
        # Render generated code
        rendered_screenshot = render_with_playwright(project_path)

        # Visual audit
        audit_result = visual_auditor.compare(figma_screenshot, rendered_screenshot)

        if audit_result['score'] >= 0.95:
            # SUCCESS: Deploy
            deploy_to_vercel(project_path)
            return {
                "status": "deployed",
                "score": audit_result['score'],
                "iterations": iteration + 1,
                "url": vercel_url
            }

        # FAILURE: Self-heal
        diff_report = audit_result['issues']
        project_path = regenerate_with_constraints(design_data, diff_report)

    # After 3 iterations, flag for human review
    return {
        "status": "needs_review",
        "score": audit_result['score'],
        "iterations": 3,
        "issues": audit_result['issues']
    }
```

---

## 5. New MCP Tools to Build

### Tool 1: `visual_audit`
```python
@mcp_server.tool()
async def visual_audit(
    figma_screenshot_path: str,
    rendered_screenshot_path: str,
    threshold: float = 0.95
) -> dict:
    """Compare Figma design to rendered code."""
    return await visual_auditor.audit(figma_screenshot_path, rendered_screenshot_path, threshold)
```

### Tool 2: `render_preview`
```python
@mcp_server.tool()
async def render_preview(project_path: str, viewport_width: int = 1440, viewport_height: int = 900) -> str:
    """Render generated code and return screenshot path."""
    return await render_engine.render(project_path, viewport_width, viewport_height)
```

### Tool 3: `self_heal_code`
```python
@mcp_server.tool()
async def self_heal_code(
    project_path: str,
    diff_report: dict,
    figma_metadata: dict
) -> str:
    """Re-generate code with corrections based on visual audit."""
    return await self_healer.fix(project_path, diff_report, figma_metadata)
```

### Tool 4: `deploy_verified`
```python
@mcp_server.tool()
async def deploy_verified(
    figma_url: str,
    auto_deploy: bool = True,
    max_iterations: int = 3
) -> dict:
    """Full pipeline: Figma → Code → Verify → Deploy (with auto-healing)."""
    return await verified_figma_converter.run(figma_url, auto_deploy, max_iterations)
```

---

## 6. File Structure (New Components)

```
mcp-automation/src/
├── tools/
│   ├── verified_figma_converter.py   # NEW: Main closed-loop pipeline
│   └── production_figma_converter.py # EXISTING: Keep for fallback
│
├── verification/                       # NEW MODULE
│   ├── __init__.py
│   ├── visual_auditor.py              # Vision model comparison
│   ├── render_engine.py               # Playwright rendering
│   ├── self_healer.py                 # Auto-fix generator
│   ├── confidence_scorer.py           # Metrics calculation
│   └── screenshot_manager.py          # Image preprocessing
│
└── config.py                          # ADD: Vision model API keys
```

---

## 7. Required Dependencies

Add to `mcp-automation/requirements.txt`:
```txt
# Existing
playwright==1.40.0

# NEW for Visual Auditor
scikit-image==0.24.0          # SSIM calculations
opencv-python==4.9.0          # Image processing
anthropic==0.42.0             # Claude Vision API
openai==1.59.0                # GPT-4o Vision API
pillow==10.4.0                # Image handling (upgrade)
```

---

## 8. Environment Variables

Add to `.env`:
```bash
# Vision Models (choose one or use fallback)
OPENAI_API_KEY=sk-proj-...            # For GPT-4o-mini (fast, cheap)
ANTHROPIC_API_KEY=sk-ant-...          # For Claude 3.5 Sonnet (best accuracy)

# Visual Auditor Settings
VISUAL_AUDIT_THRESHOLD=0.95           # Min score to auto-deploy
VISUAL_AUDIT_MAX_ITERATIONS=3         # Max self-healing attempts
VISUAL_AUDIT_VIEWPORT_WIDTH=1440      # Default viewport
VISUAL_AUDIT_VIEWPORT_HEIGHT=900
```

---

## 9. VC Demo Flow (60-Second "Wow")

**Setup:**
1. Open Figma design in browser
2. GodComet hotkey overlay ready
3. Screen recording active

**Script:**
```
00:00 - Hit Ctrl+Space, type: "deploy figma https://figma.com/file/abc123"
00:05 - Overlay shows: "Extracting design..."
00:10 - "Generating React components..."
00:20 - "Rendering preview..."
00:25 - Split screen: Figma (left) | Generated (right)
00:30 - Overlay shows: "Visual Audit: 94% match - Self-healing..."
00:35 - [Code automatically regenerates]
00:40 - "Visual Audit: 97% match - Deploying..."
00:50 - "Live at: https://project-abc.vercel.app"
00:55 - Open URL in browser - PERFECT match to Figma
01:00 - [End]
```

**VC Pitch Line:**
> "Unlike Cursor or Copilot, we don't just write code - we guarantee it looks pixel-perfect. Our Visual Auditor achieves 95%+ accuracy autonomously, with zero human iteration."

---

## 10. Competitive Moat Analysis

| Feature | Cursor | v0.dev | Bolt.new | **GodComet** |
|---------|--------|--------|----------|--------------|
| **Figma Integration** | ❌ | ✅ | ❌ | ✅ |
| **Auto Code Gen** | ✅ | ✅ | ✅ | ✅ |
| **Visual Verification** | ❌ | ❌ | ❌ | ✅ **Unique** |
| **Self-Healing** | ❌ | ❌ | ❌ | ✅ **Unique** |
| **Confidence Score** | ❌ | ❌ | ❌ | ✅ **Unique** |
| **Auto Deploy** | ❌ | ✅ | ✅ | ✅ |
| **Iterations Required** | Many | 3-5 | 2-4 | **0-1** ✅ |

**The Billion-Dollar Question:**
> "Can your AI guarantee my designs look perfect without me checking?"

**Only GodComet can answer YES.**

---

## 11. Technical Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| **Vision model hallucination** | Use ensemble (GPT-4o + Claude), require 2/2 agreement |
| **Slow rendering (Playwright)** | Pre-warm browser pools, use Docker containers |
| **Infinite self-healing loops** | Hard limit at 3 iterations, then flag for human review |
| **Cost (Vision API calls)** | Use GPT-4o-mini ($0.15/1M tokens), cache Figma screenshots |
| **False positives (95% threshold too strict)** | Make threshold configurable per project type |

---

## 12. Success Metrics for Beta

- **Accuracy:** 95%+ match on 50 test designs
- **Speed:** <60 seconds for full pipeline (extract → verify → deploy)
- **Automation:** 80% of designs deploy with 0 human edits
- **Self-Healing:** 70% of <95% scores fixed in 1 iteration

---

## 13. Next Steps (Implementation Order)

1. ✅ **Week 1:** Build `visual_auditor.py` with GPT-4o integration
2. ✅ **Week 2:** Build `render_engine.py` with Playwright screenshots
3. ✅ **Week 3:** Build `self_healer.py` with diff-based regeneration
4. ✅ **Week 4:** Integrate into `verified_figma_converter.py` (closed-loop)
5. ✅ **Week 5:** Test on 50 designs, tune threshold and prompts
6. ✅ **Week 6:** Build VC demo UI (split-screen comparison view)
7. ✅ **Week 7:** Record demo video, prepare pitch deck

---

## Conclusion

This Visual Auditor system is the **technical moat** that makes GodComet fundable. It transforms a "code generator" into an "autonomous design-to-deployment platform" with guaranteed accuracy.

**The VC Pitch:**
> "We're not competing with Cursor. We're building the first AI that can replace a frontend engineer's entire QA process. Ship designs with confidence - our AI verifies every pixel before it goes live."

---

**Document Version:** 1.0
**Last Updated:** 2026-01-28
**Author:** GodComet Engineering Team
