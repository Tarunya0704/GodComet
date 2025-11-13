"""Cleanup Script - Remove nested .git folders from generated projects"""
import os
import shutil
from pathlib import Path

def cleanup_nested_git_repos():
    """Remove .git folders from projects/ to prevent nested repo issues"""
    
    print("=" * 60)
    print("  🧹 Cleaning up nested git repositories")
    print("=" * 60)
    print()
    
    projects_dir = Path("projects")
    
    if not projects_dir.exists():
        print("✅ No projects/ folder found - nothing to clean")
        return
    
    removed = []
    
    # Find all .git folders in projects
    for project_folder in projects_dir.iterdir():
        if project_folder.is_dir():
            git_dir = project_folder / ".git"
            if git_dir.exists():
                try:
                    shutil.rmtree(git_dir)
                    removed.append(str(project_folder.name))
                    print(f"✅ Removed .git from: {project_folder.name}")
                except Exception as e:
                    print(f"❌ Failed to remove from {project_folder.name}: {e}")
    
    print()
    print("=" * 60)
    
    if removed:
        print(f"✅ Cleaned up {len(removed)} projects:")
        for name in removed:
            print(f"   • {name}")
        print()
        print("Now you can safely run:")
        print("  git add .")
        print("  git commit -m 'Your message'")
    else:
        print("✅ No nested .git folders found")
    
    print("=" * 60)

if __name__ == "__main__":
    try:
        cleanup_nested_git_repos()
    except Exception as e:
        print(f"\n❌ Error: {e}")