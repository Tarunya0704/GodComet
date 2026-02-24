"""
Environment Variables Diagnostic Tool
Checks if .env file is loaded correctly
"""

import os
from pathlib import Path
from dotenv import load_dotenv

print("=" * 80)
print("🔍 ENVIRONMENT VARIABLES DIAGNOSTIC")
print("=" * 80)

# Load .env file
env_path = Path(__file__).parent.parent / '.env'
print(f"\n📁 Looking for .env at: {env_path}")
print(f"   File exists: {env_path.exists()}")

if env_path.exists():
    print(f"   File size: {env_path.stat().st_size} bytes")

# Load environment
load_dotenv(dotenv_path=env_path)
print(f"\n✅ load_dotenv() called")

# Check required keys
required_keys = {
    "GROQ_API_KEY": "Code generation + Vision",
    "FIGMA_TOKEN": "Design extraction",
    "GITHUB_TOKEN": "Repo creation (optional)",
    "VERCEL_TOKEN": "Deployment (optional)",
    "OPENAI_API_KEY": "OpenAI vision (fallback)",
    "ANTHROPIC_API_KEY": "Claude vision (fallback)"
}

print("\n" + "=" * 80)
print("🔑 API KEYS STATUS")
print("=" * 80)

found_count = 0
for key, description in required_keys.items():
    value = os.getenv(key)
    if value:
        # Mask the key for security
        masked = value[:8] + "..." + value[-4:] if len(value) > 12 else "***"
        print(f"✅ {key}: {masked}")
        print(f"   Purpose: {description}")
        found_count += 1
    else:
        print(f"❌ {key}: NOT FOUND")
        print(f"   Purpose: {description}")

print("\n" + "=" * 80)
print(f"📊 SUMMARY: {found_count}/{len(required_keys)} keys found")
print("=" * 80)

# Minimum requirements
groq_key = os.getenv("GROQ_API_KEY")
figma_token = os.getenv("FIGMA_TOKEN")

print("\n🎯 MINIMUM REQUIREMENTS:")
if groq_key and figma_token:
    print("✅ You have the minimum required keys!")
    print("   - GROQ_API_KEY (for code gen + vision)")
    print("   - FIGMA_TOKEN (for design extraction)")
    print("\n   You can now run: python agentic_os.py")
else:
    print("❌ Missing required keys:")
    if not groq_key:
        print("   - GROQ_API_KEY (get from: https://console.groq.com/keys)")
    if not figma_token:
        print("   - FIGMA_TOKEN (get from: https://www.figma.com/developers/api#access-tokens)")

# Check .env file format
print("\n" + "=" * 80)
print("📝 .ENV FILE FORMAT CHECK")
print("=" * 80)

if env_path.exists():
    with open(env_path, 'r') as f:
        lines = f.readlines()

    print(f"Total lines: {len(lines)}")

    issues = []
    for i, line in enumerate(lines, 1):
        line = line.strip()
        if line and not line.startswith('#'):
            if '=' not in line:
                issues.append(f"Line {i}: Missing '=' sign: {line}")
            elif line.startswith(' '):
                issues.append(f"Line {i}: Starts with space (should not): {line}")

    if issues:
        print("\n⚠️  Potential issues found:")
        for issue in issues:
            print(f"   {issue}")
    else:
        print("✅ .env file format looks good!")

    # Show first few lines (masked)
    print("\n📄 First 5 lines of .env (values masked):")
    for i, line in enumerate(lines[:5], 1):
        if '=' in line and not line.strip().startswith('#'):
            key, _ = line.split('=', 1)
            print(f"   {i}. {key.strip()}=***")
        else:
            print(f"   {i}. {line.strip()}")
else:
    print("❌ .env file not found!")
    print("\n   Create it at: C:\\Users\\tarun\\Desktop\\GodComet\\mcp-automation\\.env")
    print("\n   Minimal content:")
    print("   GROQ_API_KEY=gsk_your_key_here")
    print("   FIGMA_TOKEN=figd_your_token_here")

print("\n" + "=" * 80)
