"""
GitHub Token Diagnosis Script
Run this to find out why GITHUB_TOKEN isn't loading
"""
import os
from pathlib import Path
from dotenv import load_dotenv

print("\n" + "="*60)
print("🔍 GITHUB TOKEN DIAGNOSIS")
print("="*60)

# Check .env file location
env_path = Path('.env')
print(f"\n1. Checking .env file:")
print(f"   Location: {env_path.absolute()}")
print(f"   Exists: {env_path.exists()}")

if not env_path.exists():
    print("   ❌ .env file not found!")
    print(f"   Current dir: {os.getcwd()}")
    exit(1)

# Read raw .env file
print(f"\n2. Reading .env file:")
with open('.env', 'r', encoding='utf-8') as f:
    lines = f.readlines()

print(f"   Total lines: {len(lines)}")

github_lines = []
for i, line in enumerate(lines, 1):
    if 'GITHUB_TOKEN' in line:
        github_lines.append((i, line))
        # Don't show full token
        if '=' in line:
            display = line.split('=')[0] + "=***"
        else:
            display = line.strip()
        print(f"   Line {i}: {display}")

if not github_lines:
    print("   ❌ GITHUB_TOKEN not found in .env!")
    print("\n   Add this line to your .env file:")
    print("   GITHUB_TOKEN=ghp_your_token_here")
    exit(1)

# Analyze the first GITHUB_TOKEN line
line_num, line_content = github_lines[0]
print(f"\n3. Analyzing GITHUB_TOKEN line {line_num}:")

issues = []

# Check if commented
if line_content.strip().startswith('#'):
    issues.append("❌ CRITICAL: Line is commented out! Remove the # at the start")
    print("   ❌ Line is commented out!")
    print(f"   Current: {line_content.strip()}")
    print(f"   Should be: {line_content.strip()[1:].strip()}")

# Check format
if '=' not in line_content:
    issues.append("❌ CRITICAL: Missing '=' sign")
else:
    parts = line_content.split('=', 1)
    key = parts[0].strip()
    value = parts[1].strip() if len(parts) > 1 else ""
    
    # Check key
    if key != 'GITHUB_TOKEN':
        if key.startswith('#'):
            issues.append(f"❌ Key is commented: '{key}'")
        else:
            issues.append(f"⚠️  Key has extra characters: '{key}'")
    
    # Check for spaces around =
    if ' = ' in line_content:
        issues.append("⚠️  Has spaces around '=' (remove them)")
        print(f"   ⚠️  Has spaces around '='")
        print(f"   Change: GITHUB_TOKEN = {value[:10]}...")
        print(f"   To:     GITHUB_TOKEN={value[:10]}...")
    
    # Check value
    if not value:
        issues.append("❌ CRITICAL: Value is empty!")
    else:
        # Check quotes
        if value.startswith('"') or value.startswith("'"):
            issues.append("⚠️  Has quotes (remove them)")
            print(f"   ⚠️  Has quotes around token")
            print(f"   Change: GITHUB_TOKEN=\"{value[1:-1][:10]}...\"")
            print(f"   To:     GITHUB_TOKEN={value[1:-1][:10]}...")
            value = value.strip('"\'')
        
        # Check spaces
        if value != value.strip():
            issues.append("⚠️  Has leading/trailing spaces")
        
        # Check token format
        if value and not value.startswith('ghp_') and not value.startswith('github_pat_'):
            issues.append(f"⚠️  Token format unusual (should start with ghp_ or github_pat_)")
            print(f"   ⚠️  Token doesn't start with ghp_ or github_pat_")
            print(f"   Your token starts with: {value[:10]}")

if not issues:
    print("   ✅ Format looks correct!")
else:
    print(f"\n   Found {len(issues)} issue(s):")
    for issue in issues:
        print(f"   {issue}")

# Load with dotenv
print(f"\n4. Loading with dotenv:")
load_dotenv(env_path)
token = os.getenv('GITHUB_TOKEN')

if token:
    print(f"   ✅ Token loaded successfully!")
    print(f"   Length: {len(token)} characters")
    print(f"   Starts with: {token[:10]}...")
    
    # Validate token format
    if token.startswith('ghp_'):
        print(f"   ✅ Classic token format (ghp_)")
    elif token.startswith('github_pat_'):
        print(f"   ✅ Fine-grained token format (github_pat_)")
    else:
        print(f"   ⚠️  Unusual token format")
else:
    print(f"   ❌ Token is None after loading!")
    print(f"\n   This means dotenv couldn't find/parse the line.")
    print(f"   Check for:")
    print(f"   - Line is commented out with #")
    print(f"   - Unusual characters or encoding")
    print(f"   - File encoding issues (should be UTF-8)")

# Test Config import
print(f"\n5. Testing Config class:")
try:
    # Import config
    from src.config import Config
    print("   ✅ Config imported successfully")
    
    # Check attribute
    if hasattr(Config, 'GITHUB_TOKEN'):
        print("   ✅ Config.GITHUB_TOKEN attribute exists")
        
        if Config.GITHUB_TOKEN:
            print(f"   ✅ Config.GITHUB_TOKEN has value: {Config.GITHUB_TOKEN[:10]}...")
        else:
            print(f"   ❌ Config.GITHUB_TOKEN is None or empty!")
            print(f"\n   This is strange - dotenv loaded it but Config doesn't have it.")
            print(f"   Try restarting Python or check import order.")
    else:
        print(f"   ❌ Config.GITHUB_TOKEN attribute missing!")
    
    # Check method
    if hasattr(Config, 'is_github_configured'):
        result = Config.is_github_configured()
        if result:
            print(f"   ✅ Config.is_github_configured() = True")
        else:
            print(f"   ❌ Config.is_github_configured() = False")
            if Config.GITHUB_TOKEN:
                print(f"      BUT Config.GITHUB_TOKEN exists! Bug in is_github_configured()?")
    else:
        print(f"   ❌ is_github_configured() method missing!")
        
except ImportError as e:
    print(f"   ❌ Failed to import Config: {e}")
except Exception as e:
    print(f"   ❌ Error testing Config: {e}")

# Final summary
print("\n" + "="*60)
print("📊 SUMMARY:")
print("="*60)

if not issues and token and hasattr(Config, 'GITHUB_TOKEN') and Config.GITHUB_TOKEN:
    print("✅ Everything looks good!")
    print("   Token is loading correctly.")
    print("\n   If app_cli.py still says 'Skipping GitHub',")
    print("   the issue might be in how app_cli.py checks the config.")
elif issues:
    print("❌ Issues found in .env file:")
    for issue in issues:
        print(f"   {issue}")
    print("\n   Fix these issues in your .env file and run again.")
else:
    print("❌ Token not loading correctly")
    print("   Check the issues above.")

print("="*60 + "\n")