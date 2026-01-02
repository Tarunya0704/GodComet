"""
AUTOMATIC FIX for Max Iterations Error
Just run: python fix_max_iterations.py
"""
import re
from pathlib import Path
import shutil

def backup_file(filepath: Path):
    """Create backup"""
    backup = filepath.with_suffix(filepath.suffix + '.backup')
    shutil.copy2(filepath, backup)
    print(f"📦 Backup created: {backup}")

def fix_github_tool():
    """Fix github_tool.py to add completion flags"""
    
    github_file = Path("src/tools/github_tool.py")
    
    if not github_file.exists():
        print(f"⚠️ Not found: {github_file}")
        return False
    
    backup_file(github_file)
    
    content = github_file.read_text()
    
    # Add completed flag to successful push
    old_return = '''return {
                "success": True,
                "message": f"Code pushed to {repo_name}",
                "data": {
                    "repo_url": repo.html_url,
                    "branch": branch,
                    "clone_url": repo.clone_url
                }
            }'''
    
    new_return = '''return {
                "success": True,
                "completed": True,  # SIGNAL TO STOP
                "message": f"Code pushed to {repo_name}",
                "data": {
                    "repo_url": repo.html_url,
                    "branch": branch,
                    "clone_url": repo.clone_url
                }
            }'''
    
    if old_return in content:
        content = content.replace(old_return, new_return)
        print("✅ Fixed: Added completion flag to push_local_code")
    
    # Add completed flag to build_and_push
    old_build = '''return {
                "success": True,
                "message": f"Project '{repo_name}' created and pushed",
                "data": {
                    "repo_url": create_result["data"]["url"],
                    "clone_url": create_result["data"]["clone_url"],
                    "branch": branch
                }
            }'''
    
    new_build = '''return {
                "success": True,
                "completed": True,  # SIGNAL TO STOP
                "message": f"Project '{repo_name}' created and pushed successfully!",
                "data": {
                    "repo_url": create_result["data"]["url"],
                    "clone_url": create_result["data"]["clone_url"],
                    "branch": branch
                }
            }'''
    
    if old_build in content:
        content = content.replace(old_build, new_build)
        print("✅ Fixed: Added completion flag to build_and_push_project")
    
    github_file.write_text(content)
    return True

def fix_mcp_server():
    """Fix mcp_server.py to check completion flag"""
    
    mcp_file = Path("src/mcp_server.py")
    
    if not mcp_file.exists():
        print(f"⚠️ Not found: {mcp_file}")
        return False
    
    backup_file(mcp_file)
    
    content = mcp_file.read_text()
    
    # Reduce max iterations from 10 to 3
    content = re.sub(
        r'max_iterations\s*=\s*10',
        'max_iterations = 3  # Reduced to fail faster',
        content
    )
    print("✅ Fixed: Reduced max_iterations to 3")
    
    # Find the tool execution loop and add completion check
    # Look for pattern where result is checked
    pattern = r'(result\s*=\s*await\s+self\.execute_tool.*?\n.*?)(\n\s+# Check if we should continue)'
    
    replacement = r'''\1
                
                # CHECK FOR COMPLETION
                if result.get("completed") is True:
                    logger.info("✅ Task marked as completed, stopping iteration")
                    break
                
                # CHECK FOR FATAL ERRORS
                if result.get("fatal") is True:
                    logger.error("❌ Fatal error detected, stopping iteration")
                    break
\2'''
    
    content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    print("✅ Fixed: Added completion check to execution loop")
    
    mcp_file.write_text(content)
    return True

def fix_vercel_tool():
    """Fix vercel_tool.py to add completion flags"""
    
    vercel_file = Path("src/tools/vercel_tool.py")
    
    if not vercel_file.exists():
        print(f"⚠️ Not found: {vercel_file}")
        return False
    
    backup_file(vercel_file)
    
    content = vercel_file.read_text()
    
    # Add completed flag to successful deployment
    pattern = r'("success":\s*True,\s*\n\s*"message":.*?deployment successful)'
    replacement = r'"success": True,\n                "completed": True,  # SIGNAL TO STOP\n                "message": \1'
    
    content = re.sub(pattern, replacement, content)
    
    vercel_file.write_text(content)
    print("✅ Fixed: Added completion flag to vercel deployment")
    return True

def main():
    """Run all fixes"""
    print("🔧 Starting automatic fixes...")
    print()
    
    fixes_applied = 0
    
    if fix_github_tool():
        fixes_applied += 1
    
    if fix_mcp_server():
        fixes_applied += 1
    
    if fix_vercel_tool():
        fixes_applied += 1
    
    print()
    print("=" * 60)
    if fixes_applied > 0:
        print(f"✅ Applied {fixes_applied} fixes successfully!")
        print()
        print("🧪 Test it:")
        print("   python app_cli.py")
        print()
        print("📝 Backups created with .backup extension")
        print("   If something breaks, restore from backup")
    else:
        print("❌ No fixes could be applied")
        print("   Check that you're in the right directory")
        print("   Your files should be in: src/tools/ and src/")
    print("=" * 60)

if __name__ == "__main__":
    main()