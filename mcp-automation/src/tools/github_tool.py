# """GitHub automation tool using PyGithub"""
# import os
# import subprocess
# from github import Github, GithubException
# from typing import Dict, Any, Optional
# import logging
# from pathlib import Path

# logger = logging.getLogger(__name__)

# class GitHubTool:
#     """GitHub repository management and deployment"""
    
#     def __init__(self, access_token: str):
#         """Initialize GitHub client"""
#         try:
#             self.github = Github(access_token)
#             self.user = self.github.get_user()
#             logger.info(f"✅ GitHub authenticated as: {self.user.login}")
#         except Exception as e:
#             logger.error(f"GitHub authentication failed: {e}")
#             raise
    
#     async def create_repo(self, repo_name: str, description: str = "", private: bool = False) -> Dict[str, Any]:
#         """Create a new GitHub repository"""
#         try:
#             logger.info(f"Creating repository: {repo_name}")
            
#             # Check if repo already exists
#             try:
#                 existing_repo = self.user.get_repo(repo_name)
#                 return {
#                     "success": False,
#                     "error": f"Repository '{repo_name}' already exists",
#                     "data": {"url": existing_repo.html_url}
#                 }
#             except GithubException:
#                 # Repo doesn't exist, proceed with creation
#                 pass
            
#             # Create repository
#             repo = self.user.create_repo(
#                 name=repo_name,
#                 description=description,
#                 private=private,
#                 auto_init=False  # Don't initialize with README
#             )
            
#             logger.info(f"✅ Repository created: {repo.html_url}")
            
#             return {
#                 "success": True,
#                 "message": f"Repository '{repo_name}' created successfully",
#                 "data": {
#                     "name": repo_name,
#                     "url": repo.html_url,
#                     "clone_url": repo.clone_url,
#                     "ssh_url": repo.ssh_url
#                 }
#             }
            
#         except Exception as e:
#             logger.error(f"Failed to create repository: {e}")
#             return {"success": False, "error": str(e)}
    
#     async def push_local_code(self, repo_name: str, local_path: str = ".", branch: str = "main") -> Dict[str, Any]:
#         """Initialize git and push local code to GitHub"""
#         try:
#             logger.info(f"Pushing code from {local_path} to {repo_name}")
            
#             # Get repository
#             try:
#                 repo = self.user.get_repo(repo_name)
#             except GithubException:
#                 return {
#                     "success": False,
#                     "error": f"Repository '{repo_name}' not found. Create it first."
#                 }
            
#             local_path = Path(local_path).resolve()
            
#             # Check if .git exists
#             git_dir = local_path / ".git"
#             is_git_repo = git_dir.exists()
            
#             commands = []
            
#             if not is_git_repo:
#                 # Initialize git
#                 commands.extend([
#                     ["git", "init"],
#                     ["git", "branch", "-M", branch],
#                 ])
            
#             # Add remote (remove if exists, then add)
#             commands.extend([
#                 ["git", "remote", "remove", "origin"],  # This will fail if no remote, that's ok
#                 ["git", "remote", "add", "origin", repo.clone_url],
#             ])
            
#             # Stage, commit, and push
#             commands.extend([
#                 ["git", "add", "."],
#                 ["git", "commit", "-m", "Initial commit via MCP Automation"],
#                 ["git", "push", "-u", "origin", branch],
#             ])
            
#             # Execute commands
#             results = []
#             for cmd in commands:
#                 try:
#                     result = subprocess.run(
#                         cmd,
#                         cwd=str(local_path),
#                         capture_output=True,
#                         text=True,
#                         timeout=30
#                     )
                    
#                     cmd_str = " ".join(cmd)
#                     if result.returncode == 0:
#                         logger.info(f"✅ {cmd_str}")
#                         results.append(f"✅ {cmd_str}")
#                     else:
#                         # Some commands are expected to fail (like removing non-existent remote)
#                         if "remote remove" not in cmd_str:
#                             logger.warning(f"⚠️ {cmd_str}: {result.stderr}")
#                         results.append(f"⚠️ {cmd_str}")
                        
#                 except subprocess.TimeoutExpired:
#                     logger.error(f"Command timeout: {cmd}")
#                     results.append(f"❌ Timeout: {' '.join(cmd)}")
#                 except Exception as e:
#                     logger.error(f"Command failed: {cmd} - {e}")
#                     results.append(f"❌ Failed: {' '.join(cmd)}")
            
#             return {
#                 "success": True,
#                 "message": f"Code pushed to {repo_name}",
#                 "data": {
#                     "repo_url": repo.html_url,
#                     "branch": branch,
#                     "steps": results
#                 }
#             }
            
#         except Exception as e:
#             logger.error(f"Failed to push code: {e}")
#             return {"success": False, "error": str(e)}
    
#     async def generate_readme(self, local_path: str = ".") -> Dict[str, Any]:
#         """Generate README.md based on project structure"""
#         try:
#             logger.info("Generating README.md")
            
#             local_path = Path(local_path).resolve()
            
#             # Scan project structure
#             python_files = list(local_path.rglob("*.py"))
#             config_files = list(local_path.glob("*.env*")) + list(local_path.glob("*.json")) + list(local_path.glob("*.yaml"))
            
#             # Detect main features
#             features = []
#             if any("browser" in str(f) for f in python_files):
#                 features.append("🌐 Browser Automation (Playwright)")
#             if any("jira" in str(f) for f in python_files):
#                 features.append("📋 Jira Integration")
#             if any("github" in str(f) for f in python_files):
#                 features.append("🐙 GitHub Integration")
#             if any("aws" in str(f) for f in python_files):
#                 features.append("☁️ AWS Integration")
#             if any("vercel" in str(f) for f in python_files):
#                 features.append("▲ Vercel Deployment")
            
#             # Generate README content
#             readme_content = f"""# MCP Automation Tool

# ⚡ Ultra-fast AI-powered automation system using MCP (Model Context Protocol) and Groq AI.

# ## ✨ Features

# {chr(10).join(f"- {feature}" for feature in features)}
# - 🤖 AI-powered command execution
# - 📸 Visual automation with screenshots
# - 📄 Document parsing (Word/PDF)

# ## 🚀 Quick Start

# ### Prerequisites

# - Python 3.8+
# - Groq API Key ([Get one here](https://console.groq.com/))
# - GitHub Token (optional, for GitHub features)
# - Jira credentials (optional, for Jira features)

# ### Installation

# 1. Clone the repository:
# ```bash
# git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git
# cd YOUR_REPO
# ```

# 2. Install dependencies:
# ```bash
# pip install -r requirements.txt
# ```

# 3. Configure environment variables in `.env`:
# ```env
# GROQ_API_KEY=your_groq_api_key
# GITHUB_TOKEN=your_github_token
# JIRA_URL=https://your-domain.atlassian.net
# JIRA_EMAIL=your_email@example.com
# JIRA_API_TOKEN=your_jira_token
# ```

# ### Usage

# Run the CLI application:
# ```bash
# python app_cli.py
# ```

# #### Example Commands

# **Browser Automation:**
# - `play music on youtube`
# - `go to google.com`
# - `take a screenshot`

# **GitHub Automation:**
# - `create github repo my-new-project`
# - `build this project and push to github`
# - `generate readme for this project`

# **Jira Automation:**
# - `complete jira assignment "documents/Assignment.docx"`
# - `complete jira assignment with screenshots`

# **Deployment:**
# - `deploy this on vercel`

# **File Operations:**
# - `list files`
# - `read file config.py`

# ## 🏗️ Project Structure

# ```
# {local_path.name}/
# ├── src/
# │   ├── tools/
# │   │   ├── browser_tool.py      # Browser automation
# │   │   ├── github_tool.py       # GitHub operations
# │   │   ├── vercel_tool.py       # Vercel deployment
# │   │   ├── jira_tool.py         # Jira integration
# │   │   └── document_parser.py   # Document parsing
# │   ├── ai_client.py             # AI client (Groq)
# │   ├── mcp_server.py            # MCP server
# │   ├── config.py                # Configuration
# │   └── database.py              # Task logging
# ├── app_cli.py                    # CLI entry point
# ├── documents/                    # Document storage
# ├── screenshots/                  # Screenshot output
# └── .env                          # Environment config
# ```

# ## 🔧 Configuration

# ### Groq AI
# Get your API key from [Groq Console](https://console.groq.com/)

# ### GitHub
# 1. Go to GitHub Settings → Developer settings → Personal access tokens
# 2. Generate new token with `repo` permissions
# 3. Add to `.env` as `GITHUB_TOKEN`

# ### Jira
# 1. Go to [Atlassian API tokens](https://id.atlassian.com/manage-profile/security/api-tokens)
# 2. Create API token
# 3. Add credentials to `.env`

# ## 📝 Available Tools

# - **browser_navigate** - Navigate to URLs
# - **youtube_play** - Search and play YouTube videos
# - **browser_screenshot** - Capture screenshots
# - **github_create_repo** - Create GitHub repositories
# - **github_push_code** - Push local code to GitHub
# - **vercel_deploy** - Deploy to Vercel
# - **jira_create_assignment** - Create Jira tasks
# - **file_read** / **file_write** - File operations
# - **list_directory** - List directory contents

# ## 🤝 Contributing

# Contributions are welcome! Please feel free to submit a Pull Request.

# ## 📄 License

# MIT License

# ## 🙏 Acknowledgments

# - Powered by [Groq](https://groq.com/) - Ultra-fast AI inference
# - Built with [MCP](https://modelcontextprotocol.io/) - Model Context Protocol
# - Browser automation by [Playwright](https://playwright.dev/)

# ---

# ⚡ Built with MCP Automation Tool
# """
            
#             # Write README
#             readme_path = local_path / "README.md"
#             with open(readme_path, "w", encoding="utf-8") as f:
#                 f.write(readme_content)
            
#             logger.info(f"✅ README.md generated at {readme_path}")
            
#             return {
#                 "success": True,
#                 "message": "README.md generated successfully",
#                 "data": {
#                     "path": str(readme_path),
#                     "features": len(features)
#                 }
#             }
            
#         except Exception as e:
#             logger.error(f"Failed to generate README: {e}")
#             return {"success": False, "error": str(e)}
    
#     async def build_and_push_project(self, repo_name: str, description: str = "MCP Automation Project", local_path: str = ".") -> Dict[str, Any]:
#         """Complete workflow: Generate README, create repo, and push code"""
#         try:
#             results = []
            
#             # Step 1: Generate README
#             logger.info("Step 1/3: Generating README...")
#             readme_result = await self.generate_readme(local_path)
#             results.append(f"📝 README: {readme_result.get('message', 'Generated')}")
            
#             # Step 2: Create repository
#             logger.info("Step 2/3: Creating GitHub repository...")
#             create_result = await self.create_repo(repo_name, description)
            
#             if not create_result["success"] and "already exists" not in create_result.get("error", ""):
#                 return create_result
            
#             results.append(f"📦 Repo: {create_result.get('message', 'Ready')}")
            
#             # Step 3: Push code
#             logger.info("Step 3/3: Pushing code to GitHub...")
#             push_result = await self.push_local_code(repo_name, local_path)
#             results.append(f"🚀 Push: {push_result.get('message', 'Completed')}")
            
#             repo_url = create_result.get("data", {}).get("url", "")
            
#             return {
#                 "success": True,
#                 "message": f"Project built and pushed to GitHub successfully!",
#                 "data": {
#                     "repo_name": repo_name,
#                     "repo_url": repo_url,
#                     "steps": results
#                 }
#             }
            
#         except Exception as e:
#             logger.error(f"Build and push failed: {e}")
#             return {"success": False, "error": str(e)}

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