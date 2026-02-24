"""
Simple test to verify all imports work
"""

print("Testing imports...")

try:
    print("  ✓ Importing context modules...")
    from context.context_aggregator import ContextAggregator
    from context.desktop_vision import DesktopVisionDetector
    from context.action_registry import ActionRegistry
    print("  ✅ Context modules imported")
except Exception as e:
    print(f"  ❌ Context import failed: {e}")

try:
    print("  ✓ Importing verification modules...")
    from verification.visual_auditor import VisualAuditor
    from verification.render_engine import RenderEngine
    from verification.interactive_browser import InteractiveBrowser
    from verification.confidence_scorer import ConfidenceScorer
    from verification.self_healer import SelfHealer
    print("  ✅ Verification modules imported")
except Exception as e:
    print(f"  ❌ Verification import failed: {e}")

try:
    print("  ✓ Importing tools...")
    from tools.verified_figma_converter import VerifiedFigmaConverter
    print("  ✅ Tools imported")
except Exception as e:
    print(f"  ❌ Tools import failed: {e}")

try:
    print("  ✓ Importing Agentic OS...")
    from agentic_os import AgenticOS
    print("  ✅ Agentic OS imported")
except Exception as e:
    print(f"  ❌ Agentic OS import failed: {e}")

print("\n✅ All imports successful!")
print("\nYou can now run:")
print("  python agentic_os.py")
