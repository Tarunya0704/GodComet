"""Vercel deployment automation tool"""
import subprocess
import json
import os
import re
from typing import Dict, Any, Optional
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class VercelTool:
    """Vercel deployment automation"""
    
    def __init__(self, token: Optional[str] = None):
        """Initialize Vercel tool"""
        self.token = token or os.getenv("VERCEL_TOKEN")
        if self.token:
            os.environ["VERCEL_TOKEN"] = self.token
            logger.info("✅ Vercel token configured")
    
    async def check_vercel_cli(self) -> bool:
        """Check if Vercel CLI is installed"""
        try:
            result = subprocess.run(
                "vercel --version",
                capture_output=True,
                text=True,
                timeout=5,
                shell=True  # CRITICAL for Windows
            )
            return result.returncode == 0
        except Exception:
            return False
    
    async def install_vercel_cli(self) -> Dict[str, Any]:
        """Install Vercel CLI"""
        try:
            logger.info("Installing Vercel CLI...")
            
            result = subprocess.run(
                "npm install -g vercel",
                capture_output=True,
                text=True,
                timeout=120,
                shell=True  # CRITICAL for Windows
            )
            
            if result.returncode == 0:
                logger.info("✅ Vercel CLI installed")
                return {"success": True, "message": "Vercel CLI installed successfully"}
            else:
                return {"success": False, "error": result.stderr}
                
        except Exception as e:
            logger.error(f"Failed to install Vercel CLI: {e}")
            return {"success": False, "error": str(e)}
    
    async def create_vercel_config(self, local_path: str = ".") -> Dict[str, Any]:
        """Create vercel.json configuration"""
        try:
            local_path = Path(local_path).resolve()
            
            # Detect project type
            has_package_json = (local_path / "package.json").exists()
            has_requirements = (local_path / "requirements.txt").exists()
            has_next = (local_path / "next.config.js").exists()
            
            vercel_config = {}
            
            if has_next:
                # Next.js project
                vercel_config = {
                    "version": 2,
                    "framework": "nextjs"
                }
            elif has_package_json:
                # Node.js project
                vercel_config = {
                    "version": 2,
                    "builds": [
                        {
                            "src": "package.json",
                            "use": "@vercel/node"
                        }
                    ]
                }
            elif has_requirements:
                # Python project (for static/API)
                vercel_config = {
                    "version": 2,
                    "builds": [
                        {
                            "src": "api/*.py",
                            "use": "@vercel/python"
                        }
                    ],
                    "routes": [
                        {
                            "src": "/(.*)",
                            "dest": "api/index.py"
                        }
                    ]
                }
            else:
                # Static site
                vercel_config = {
                    "version": 2
                }
            
            # Write vercel.json
            config_path = local_path / "vercel.json"
            with open(config_path, "w") as f:
                json.dump(vercel_config, f, indent=2)
            
            logger.info(f"✅ Created vercel.json at {config_path}")
            
            return {
                "success": True,
                "message": "Vercel configuration created",
                "data": {"config_path": str(config_path)}
            }
            
        except Exception as e:
            logger.error(f"Failed to create Vercel config: {e}")
            return {"success": False, "error": str(e)}
    
    async def deploy(self, local_path: str = ".", production: bool = True) -> Dict[str, Any]:
        """Deploy project to Vercel"""
        try:
            logger.info(f"Deploying to Vercel from {local_path}")
            
            # Check if Vercel CLI is installed
            if not await self.check_vercel_cli():
                logger.info("Vercel CLI not found, installing...")
                install_result = await self.install_vercel_cli()
                if not install_result["success"]:
                    return install_result
            
            local_path = Path(local_path).resolve()
            
            # Create vercel.json if it doesn't exist
            if not (local_path / "vercel.json").exists():
                config_result = await self.create_vercel_config(str(local_path))
                if not config_result["success"]:
                    logger.warning("Could not create vercel.json, continuing anyway...")
            
            # Build deployment command
            cmd_parts = ["vercel"]
            
            if production:
                cmd_parts.append("--prod")
            
            # Add yes flag for non-interactive
            cmd_parts.append("--yes")
            
            # Set token if available
            if self.token:
                cmd_parts.extend(["--token", self.token])
            
            # Join command for Windows
            cmd = " ".join(cmd_parts)
            
            logger.info(f"Running: {cmd}")
            
            # Run deployment
            result = subprocess.run(
                cmd,
                cwd=str(local_path),
                capture_output=True,
                text=True,
                timeout=300,  # 5 minutes timeout
                shell=True  # CRITICAL for Windows
            )
            
            if result.returncode == 0:
                # Extract deployment URL from output.
                # Modern Vercel CLI lines look like:
                #   ✅  Production: https://project-abc123.vercel.app [2s]
                # Older versions omit the emoji prefix.
                # Use regex so we're immune to prefix/suffix changes.
                output_lines = result.stdout.split('\n')
                deployment_url = None

                for line in output_lines:
                    match = re.search(r'https://[^\s]+\.vercel\.app[^\s]*', line)
                    if match:
                        deployment_url = match.group(0).rstrip('/')
                        break

                # Fallback: grab any https:// URL from the output if no .vercel.app found
                if not deployment_url:
                    for line in output_lines:
                        match = re.search(r'https://[^\s]+', line)
                        if match:
                            deployment_url = match.group(0).rstrip('/')
                            break
                
                logger.info(f"✅ Deployed to: {deployment_url}")
                
                return {
                    "success": True,
                    "message": f"Deployed to Vercel successfully",
                    "data": {
                        "url": deployment_url,
                        "production": production,
                        "output": result.stdout
                    }
                }
            else:
                logger.error(f"Deployment failed: {result.stderr}")
                return {
                    "success": False,
                    "error": result.stderr or "Deployment failed"
                }
                
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "Deployment timeout (>5 minutes)"
            }
        except Exception as e:
            logger.error(f"Deployment failed: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_deployments(self, limit: int = 5) -> Dict[str, Any]:
        """List recent deployments"""
        try:
            # First check if CLI is available
            if not await self.check_vercel_cli():
                return {
                    "success": False,
                    "error": "Vercel CLI not found. Install: npm install -g vercel"
                }
            
            cmd_parts = ["vercel", "list", "--json"]
            
            if self.token:
                cmd_parts.extend(["--token", self.token])
            
            # Join command for Windows
            cmd = " ".join(cmd_parts)
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                shell=True  # CRITICAL for Windows
            )
            
            if result.returncode == 0:
                try:
                    deployments = json.loads(result.stdout)
                    return {
                        "success": True,
                        "message": f"Found {len(deployments)} deployments",
                        "data": {
                            "deployments": deployments[:limit]
                        }
                    }
                except json.JSONDecodeError:
                    return {
                        "success": False,
                        "error": "Failed to parse deployment list"
                    }
            else:
                error_msg = result.stderr or "Unknown error"
                if "not found" in error_msg.lower() or "not recognized" in error_msg.lower():
                    return {
                        "success": False,
                        "error": "Vercel CLI not found. Install: npm install -g vercel"
                    }
                return {"success": False, "error": error_msg}
                
        except FileNotFoundError:
            return {
                "success": False,
                "error": "Vercel CLI not found. Install: npm install -g vercel"
            }
        except Exception as e:
            logger.error(f"Failed to get deployments: {e}")
            return {"success": False, "error": str(e)}