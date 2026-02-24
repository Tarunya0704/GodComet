"""GitHub automation tool - FIXED with completion flags"""
import os
import subprocess
from github import Github, GithubException
from typing import Dict, Any, Optional
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class GitHubTool:
    """GitHub repository management and deployment"""
    
    def __init__(self, access_token: str):
        """Initialize GitHub client"""
        try:
            self.github = Github(access_token)
            self.user = self.github.get_user()
            logger.info(f"✅ GitHub authenticated as: {self.user.login}")
        except Exception as e:
            logger.error(f"GitHub authentication failed: {e}")
            raise
    
    async def create_repo(self, repo_name: str, description: str = "", private: bool = False) -> Dict[str, Any]:
        """Create a new GitHub repository"""
        try:
            logger.info(f"Creating repository: {repo_name}")
            
            # Check if repo already exists
            try:
                existing_repo = self.user.get_repo(repo_name)
                logger.info(f"Repository '{repo_name}' already exists, using it")
                return {
                    "success": True,
                    "data": {
                        "url": existing_repo.html_url,
                        "clone_url": existing_repo.clone_url,
                        "ssh_url": existing_repo.ssh_url
                    }
                }
            except GithubException:
                pass
            
            # Create repository
            repo = self.user.create_repo(
                name=repo_name,
                description=description,
                private=private,
                auto_init=False
            )
            
            logger.info(f"✅ Repository created: {repo.html_url}")
            
            return {
                "success": True,
                "data": {
                    "url": repo.html_url,
                    "clone_url": repo.clone_url,
                    "ssh_url": repo.ssh_url
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to create repository: {e}")
            return {
                "success": False,
                "error": str(e),
                "fatal": True  # Don't retry
            }
    
    def _run_git_command(self, cmd: list, cwd: str, timeout: int = 300) -> tuple:
        """Run a git command with proper timeout and error handling"""
        try:
            cmd_str = " ".join(cmd)
            logger.info(f"Running: {cmd_str}")
            
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            return result.returncode, result.stdout, result.stderr
            
        except subprocess.TimeoutExpired:
            logger.error(f"Command timeout after {timeout}s: {cmd}")
            return -1, "", f"Timeout after {timeout} seconds"
        except Exception as e:
            logger.error(f"Command failed: {cmd} - {e}")
            return -1, "", str(e)
    
    async def push_local_code(
        self,
        repo_name: str,
        local_path: str,
        branch: str = "main"
    ) -> Dict[str, Any]:
        """Push local code to GitHub repository"""
        try:
            local_path = Path(local_path)
            
            if not local_path.exists():
                return {
                    "success": False,
                    "error": f"Path does not exist: {local_path}",
                    "fatal": True
                }
            
            # Get repo info
            try:
                repo = self.user.get_repo(repo_name)
            except GithubException as e:
                return {
                    "success": False,
                    "error": f"Repository '{repo_name}' not found. Create it first.",
                    "fatal": True
                }
            
            logger.info(f"Pushing code from {local_path} to {repo_name}")
            
            # Initialize git if needed
            git_dir = local_path / ".git"
            if not git_dir.exists():
                logger.info("Initializing git repository")
                returncode, stdout, stderr = self._run_git_command(
                    ["git", "init"],
                    str(local_path),
                    timeout=10
                )
                if returncode != 0:
                    return {
                        "success": False,
                        "error": f"Git init failed: {stderr}",
                        "fatal": True
                    }
            
            # Configure git
            commands = [
                ["git", "config", "user.email", "automation@mcp.ai"],
                ["git", "config", "user.name", "MCP Automation"],
            ]
            
            for cmd in commands:
                self._run_git_command(cmd, str(local_path), timeout=10)
            
            # Remove existing remote
            self._run_git_command(["git", "remote", "remove", "origin"], str(local_path), timeout=10)
            
            # Add remote
            returncode, stdout, stderr = self._run_git_command(
                ["git", "remote", "add", "origin", repo.clone_url],
                str(local_path),
                timeout=10
            )
            if returncode != 0:
                return {
                    "success": False,
                    "error": f"Failed to add remote: {stderr}",
                    "fatal": True
                }
            
            # Create .gitignore
            gitignore_path = local_path / ".gitignore"
            if not gitignore_path.exists():
                with open(gitignore_path, "w") as f:
                    f.write("node_modules/\n.next/\nout/\n.DS_Store\n*.log\n.vercel\n.env*.local\ndist/\nbuild/\n")
            
            # Stage files
            returncode, stdout, stderr = self._run_git_command(
                ["git", "add", "."],
                str(local_path),
                timeout=60
            )
            if returncode != 0:
                return {
                    "success": False,
                    "error": f"Failed to stage files: {stderr}"
                }
            
            # Check if anything to commit
            returncode, stdout, stderr = self._run_git_command(
                ["git", "status", "--porcelain"],
                str(local_path),
                timeout=10
            )
            
            if not stdout.strip():
                logger.info("No changes to commit")
                return {
                    "success": True,
                    "completed": True,  # TASK DONE
                    "message": "No changes to commit",
                    "data": {"repo_url": repo.html_url}
                }
            
            # Commit
            returncode, stdout, stderr = self._run_git_command(
                ["git", "commit", "-m", "Initial commit via MCP Automation"],
                str(local_path),
                timeout=30
            )
            if returncode != 0:
                return {
                    "success": False,
                    "error": f"Commit failed: {stderr}"
                }
            
            # Create and checkout branch
            self._run_git_command(["git", "checkout", "-b", branch], str(local_path), timeout=10)
            
            # Push
            logger.info(f"Pushing to GitHub...")
            returncode, stdout, stderr = self._run_git_command(
                ["git", "push", "-u", "origin", branch],
                str(local_path),
                timeout=300
            )
            
            if returncode != 0:
                # Try with force
                logger.info("Retrying with --force...")
                returncode, stdout, stderr = self._run_git_command(
                    ["git", "push", "-u", "origin", branch, "--force"],
                    str(local_path),
                    timeout=300
                )
                
                if returncode != 0:
                    return {
                        "success": False,
                        "error": f"Push failed: {stderr}",
                        "data": {
                            "repo_url": repo.html_url,
                            "suggestion": f"Repo created. Push manually:\n  cd {local_path}\n  git push -u origin {branch}"
                        }
                    }
            
            logger.info(f"✅ Code pushed successfully to {repo.html_url}")
            
            return {
                "success": True,
                "completed": True,  # TASK DONE - STOP ITERATION
                "message": f"✅ Code pushed to {repo_name}",
                "data": {
                    "repo_url": repo.html_url,
                    "branch": branch,
                    "clone_url": repo.clone_url
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to push code: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "fatal": True
            }
    
    async def build_and_push_project(
        self,
        repo_name: str,
        description: str,
        local_path: str,
        branch: str = "main"
    ) -> Dict[str, Any]:
        """Complete workflow: Create repo + Push code"""
        try:
            # Validate path first
            if not Path(local_path).exists():
                return {
                    "success": False,
                    "error": f"Project path does not exist: {local_path}",
                    "fatal": True
                }
            
            # Step 1: Create repository
            logger.info(f"📦 Step 1/2: Creating GitHub repository '{repo_name}'")
            create_result = await self.create_repo(repo_name, description)
            
            if not create_result["success"]:
                return create_result
            
            repo_url = create_result["data"]["url"]
            logger.info(f"✅ Repository ready: {repo_url}")
            
            # Step 2: Push code
            logger.info(f"📤 Step 2/2: Pushing code to GitHub")
            push_result = await self.push_local_code(repo_name, local_path, branch)
            
            if not push_result["success"]:
                return push_result
            
            logger.info("✅✅ GitHub workflow complete!")
            
            return {
                "success": True,
                "completed": True,  # TASK DONE - STOP ITERATION
                "message": f"✅ Project '{repo_name}' created and pushed to GitHub successfully!",
                "data": {
                    "repo_url": repo_url,
                    "clone_url": create_result["data"]["clone_url"],
                    "branch": branch
                }
            }
            
        except Exception as e:
            logger.error(f"Build and push failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "fatal": True
            }
    
    async def list_repos(self, limit: int = 10) -> Dict[str, Any]:
        """List repositories"""
        try:
            repos = self.user.get_repos(sort="updated", direction="desc")
            
            repo_list = []
            for repo in repos[:limit]:
                repo_list.append({
                    "name": repo.name,
                    "description": repo.description or "",
                    "url": repo.html_url,
                    "private": repo.private,
                    "stars": repo.stargazers_count,
                    "updated": repo.updated_at.strftime("%Y-%m-%d")
                })
            
            return {
                "success": True,
                "completed": True,
                "data": {"repos": repo_list}
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "fatal": True
            }
    
    async def generate_readme(self, project_path: str, project_name: str) -> Dict[str, Any]:
        """Generate README"""
        try:
            readme_content = f"""# {project_name}

Generated by MCP Automation

## Tech Stack
- Next.js 14
- React 18
- TypeScript
- Tailwind CSS

## Setup
```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

## Build
```bash
npm run build
npm start
```

## Deploy
[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new)

---
🚀 Created with MCP Automation
"""
            
            readme_path = Path(project_path) / "README.md"
            with open(readme_path, "w", encoding="utf-8") as f:
                f.write(readme_content)
            
            logger.info(f"✅ README.md created")
            
            return {
                "success": True,
                "completed": True,
                "data": {"readme_path": str(readme_path)}
            }
            
        except Exception as e:
            logger.error(f"Failed to generate README: {e}")
            return {
                "success": False,
                "error": str(e)
            }