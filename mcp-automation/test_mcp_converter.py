"""
MCP vs REST API converter comparison test.

Usage (from mcp-automation/):
    python test_mcp_converter.py

Loads FIGMA_TOKEN from mcp-automation/.env, runs both converters against
the same Figma URL, and prints a side-by-side comparison.
"""

import asyncio
import os
import sys
import time
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
# Add src/ so "from tools.xxx import" works exactly as it does in brain.py
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE / "src"))

# ── Load .env ─────────────────────────────────────────────────────────────────
def load_env(env_path: Path):
    if not env_path.exists():
        print(f"ERROR: .env not found at {env_path}")
        sys.exit(1)
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())

load_env(HERE / ".env")

FIGMA_TOKEN = os.getenv("FIGMA_TOKEN", "")
if not FIGMA_TOKEN:
    print("ERROR: FIGMA_TOKEN not set in mcp-automation/.env")
    sys.exit(1)

TEST_URL = "https://www.figma.com/design/2goKv69fPvnKWK9bI6OzhD/IIM-Trichy-Brochure?node-id=0-1"
MCP_OUT  = HERE / "_test_output" / "mcp"
REST_OUT = HERE / "_test_output" / "rest"

# ── Helpers ───────────────────────────────────────────────────────────────────

def divider(title: str):
    width = 60
    print("\n" + "─" * width)
    print(f"  {title}")
    print("─" * width)

def count_nodes(node, _seen=None) -> int:
    """Recursively count FigmaNode objects in the tree."""
    if _seen is None:
        _seen = set()
    nid = id(node)
    if nid in _seen:
        return 0
    _seen.add(nid)
    total = 1
    for child in getattr(node, "children", []):
        total += count_nodes(child, _seen)
    return total

def tsx_first_lines(tsx_path: Path, n: int = 50) -> str:
    if not tsx_path.exists():
        return "  (file not found)"
    lines = tsx_path.read_text(encoding="utf-8").splitlines()
    snippet = "\n".join(f"  {i+1:3d}  {l}" for i, l in enumerate(lines[:n]))
    if len(lines) > n:
        snippet += f"\n  ... ({len(lines) - n} more lines)"
    return snippet

def find_first_tsx(output_dir: Path) -> Path:
    candidates = list((output_dir / "src" / "components").glob("*.tsx"))
    return candidates[0] if candidates else Path("__missing__.tsx")

# ── MCP run ───────────────────────────────────────────────────────────────────

async def run_mcp() -> dict:
    from tools.mcp_figma_converter import MCPFigmaConverter
    from tools.production_figma_converter import DesignTokenExtractor, FigmaNode

    divider("MCP CONVERTER RUN")
    MCP_OUT.mkdir(parents=True, exist_ok=True)

    converter = MCPFigmaConverter(FIGMA_TOKEN)

    # Monkey-patch convert to capture intermediate data
    _nodes      = [0]
    _components = [0]
    _mcp_ok     = [False]

    original_convert = converter._convert_via_mcp

    async def patched_convert(figma_url, output_dir, figma_screenshot_path=None):
        result = await original_convert(figma_url, output_dir, figma_screenshot_path)
        return result

    t0 = time.time()
    try:
        result = await converter.convert(figma_url=TEST_URL, output_dir=MCP_OUT)
        elapsed = time.time() - t0
        _mcp_ok[0] = result.get("success", False)
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  ❌ Exception: {e}")
        return {"success": False, "error": str(e), "elapsed": elapsed}

    print(f"  Success          : {result.get('success')}")
    print(f"  File name        : {result.get('file_name', '?')}")
    print(f"  Components found : {len(result.get('components', []))}")
    print(f"  Images downloaded: {result.get('images', 0)}")
    print(f"  Elapsed          : {elapsed:.1f}s")

    # Count tokens from tailwind.config.js
    tc = MCP_OUT / "tailwind.config.js"
    token_count = 0
    if tc.exists():
        token_count = tc.read_text().count("'#")  # rough count of hex color entries
    print(f"  Color tokens     : ~{token_count} (from tailwind.config.js)")

    # First generated component
    tsx = find_first_tsx(MCP_OUT)
    print(f"\n  First TSX file   : {tsx.name}")
    print(f"\n  First 50 lines   :\n{tsx_first_lines(tsx)}")

    result["elapsed"] = elapsed
    result["token_count"] = token_count
    return result


# ── REST run ──────────────────────────────────────────────────────────────────

async def run_rest() -> dict:
    from tools.production_figma_converter import ProductionFigmaToCode

    divider("REST API CONVERTER RUN")
    REST_OUT.mkdir(parents=True, exist_ok=True)

    converter = ProductionFigmaToCode(FIGMA_TOKEN)

    t0 = time.time()
    try:
        result = await converter.convert(
            figma_url=TEST_URL,
            output_dir=REST_OUT,
            figma_screenshot_path=None,
        )
        elapsed = time.time() - t0
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  ❌ Exception: {e}")
        return {"success": False, "error": str(e), "elapsed": elapsed}

    print(f"  Success          : {result.get('success')}")
    print(f"  File name        : {result.get('file_name', '?')}")
    print(f"  Components found : {len(result.get('components', []))}")
    print(f"  Images downloaded: {result.get('images', 0)}")
    print(f"  Elapsed          : {elapsed:.1f}s")

    tc = REST_OUT / "tailwind.config.js"
    token_count = 0
    if tc.exists():
        token_count = tc.read_text().count("'#")
    print(f"  Color tokens     : ~{token_count} (from tailwind.config.js)")

    tsx = find_first_tsx(REST_OUT)
    print(f"\n  First TSX file   : {tsx.name}")
    print(f"\n  First 50 lines   :\n{tsx_first_lines(tsx)}")

    result["elapsed"] = elapsed
    result["token_count"] = token_count
    return result


# ── Summary ───────────────────────────────────────────────────────────────────

def print_summary(mcp: dict, rest: dict):
    divider("COMPARISON SUMMARY")

    def fmt(val, fallback="?"):
        return str(val) if val is not None else fallback

    rows = [
        ("Metric",               "MCP converter",                   "REST API converter"),
        ("─" * 22,               "─" * 25,                          "─" * 25),
        ("Success",              fmt(mcp.get("success")),            fmt(rest.get("success"))),
        ("Elapsed (s)",          f"{mcp.get('elapsed', 0):.1f}",     f"{rest.get('elapsed', 0):.1f}"),
        ("Components",           fmt(len(mcp.get("components", []))), fmt(len(rest.get("components", [])))),
        ("Images",               fmt(mcp.get("images")),             fmt(rest.get("images"))),
        ("Color tokens (≈)",     fmt(mcp.get("token_count")),        fmt(rest.get("token_count"))),
        ("File name",            fmt(mcp.get("file_name")),          fmt(rest.get("file_name"))),
    ]

    col_w = [24, 27, 27]
    for row in rows:
        print("  " + "  ".join(str(cell).ljust(col_w[i]) for i, cell in enumerate(row)))

    # Verdict
    print()
    mcp_ok   = mcp.get("success")
    rest_ok  = rest.get("success")
    mcp_tok  = mcp.get("token_count", 0) or 0
    rest_tok = rest.get("token_count", 0) or 0

    if mcp_ok and mcp_tok >= rest_tok:
        print("  ✅ MCP converter produced equal or richer token data — use MCPFigmaConverter")
    elif mcp_ok and mcp_tok < rest_tok:
        print("  ⚠️  MCP converter succeeded but REST API found more tokens")
        print("     This file may not use Figma Variables — both converters work fine")
    elif not mcp_ok and rest_ok:
        print("  ⚠️  MCP failed, REST API succeeded — fallback is working correctly")
    else:
        print("  ❌ Both converters failed — check FIGMA_TOKEN and network connectivity")

    print()
    print(f"  Output dirs:")
    print(f"    MCP  → {MCP_OUT}")
    print(f"    REST → {REST_OUT}")


# ── Entry point ───────────────────────────────────────────────────────────────

async def main():
    print(f"\n{'═' * 60}")
    print(f"  MCP vs REST API Converter Test")
    print(f"  URL: {TEST_URL[:55]}...")
    print(f"{'═' * 60}")
    print(f"  FIGMA_TOKEN loaded: {'yes (' + FIGMA_TOKEN[:8] + '...)' if FIGMA_TOKEN else 'NO'}")

    mcp_result  = await run_mcp()
    rest_result = await run_rest()
    print_summary(mcp_result, rest_result)


if __name__ == "__main__":
    asyncio.run(main())
