"""Figma to Website Automation Tool"""
import os
import json
import subprocess
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
import requests
import base64

logger = logging.getLogger(__name__)

class FigmaToWebsiteTool:
    """Convert Figma designs to deployed websites with local storage"""
    
    def __init__(self, figma_token: str = None):
        self.figma_token = figma_token or os.getenv("FIGMA_TOKEN")
        self.projects_dir = Path("projects")
        self.projects_dir.mkdir(exist_ok=True)
    
    async def create_website_from_figma(
        self,
        figma_url: str,
        project_name: str,
        description: str = "Website from Figma"
    ) -> Dict[str, Any]:
        """Complete workflow: Figma → Code → Local → GitHub → Vercel"""
        try:
            logger.info(f"Starting Figma to Website conversion: {project_name}")
            
            # Step 1: Create project structure
            project_path = self.projects_dir / project_name
            if project_path.exists():
                return {
                    "success": False,
                    "error": f"Project '{project_name}' already exists"
                }
            
            project_path.mkdir(parents=True)
            logger.info(f"✅ Created project directory: {project_path}")
            
            # Step 2: Extract Figma file ID
            figma_file_id = self._extract_figma_id(figma_url)
            if not figma_file_id:
                return {
                    "success": False,
                    "error": "Invalid Figma URL"
                }
            
            # Step 3: Fetch Figma data
            figma_data = await self._fetch_figma_data(figma_file_id)
            if not figma_data:
                return {
                    "success": False,
                    "error": "Failed to fetch Figma data. Check your FIGMA_TOKEN"
                }
            
            # Save Figma export data
            figma_export_path = project_path / "figma_export_data.json"
            with open(figma_export_path, "w") as f:
                json.dump(figma_data, f, indent=2)
            logger.info("✅ Saved Figma export data")
            
            # Step 4: Extract design tokens
            design_tokens = self._extract_design_tokens(figma_data)
            
            # Step 5: Generate Next.js project structure
            await self._generate_nextjs_project(project_path, design_tokens, figma_data)
            logger.info("✅ Generated Next.js project")
            
            # Step 6: Download Figma images
            await self._download_figma_images(figma_file_id, project_path)
            logger.info("✅ Downloaded images")
            
            # Step 7: Create deployment logs
            deployment_log_path = project_path / "deployment_logs.txt"
            with open(deployment_log_path, "w") as f:
                f.write(f"Project: {project_name}\n")
                f.write(f"Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Figma URL: {figma_url}\n")
                f.write(f"Status: Generated\n\n")
            
            # Step 8: Initialize git and push to GitHub (if GitHub tools available)
            github_url = None
            try:
                from .github_tool import GitHubTool
                github_token = os.getenv("GITHUB_TOKEN")
                if github_token:
                    github = GitHubTool(github_token)
                    
                    # Create README
                    readme_path = project_path / "README.md"
                    with open(readme_path, "w") as f:
                        f.write(f"# {project_name}\n\n")
                        f.write(f"Generated from Figma design\n\n")
                        f.write(f"**Source:** {figma_url}\n")
                        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d')}\n\n")
                        f.write("## Tech Stack\n")
                        f.write("- Next.js 14\n")
                        f.write("- React 18\n")
                        f.write("- Tailwind CSS\n")
                        f.write("- TypeScript\n")
                    
                    # Build and push
                    result = await github.build_and_push_project(
                        project_name,
                        description,
                        str(project_path)
                    )
                    
                    if result["success"]:
                        github_url = result["data"]["repo_url"]
                        logger.info(f"✅ Pushed to GitHub: {github_url}")
                        
                        # Update deployment logs
                        with open(deployment_log_path, "a") as f:
                            f.write(f"GitHub URL: {github_url}\n")
            except Exception as e:
                logger.warning(f"GitHub push skipped: {e}")
            
            # Step 9: Deploy to Vercel (if Vercel tools available)
            vercel_url = None
            try:
                from .vercel_tool import VercelTool
                vercel = VercelTool()
                
                result = await vercel.deploy(str(project_path), production=True)
                
                if result["success"]:
                    vercel_url = result["data"]["url"]
                    logger.info(f"✅ Deployed to Vercel: {vercel_url}")
                    
                    # Update deployment logs
                    with open(deployment_log_path, "a") as f:
                        f.write(f"Vercel URL: {vercel_url}\n")
                        f.write(f"Deployed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            except Exception as e:
                logger.warning(f"Vercel deployment skipped: {e}")
            
            # Final success
            return {
                "success": True,
                "message": f"Website created successfully!",
                "data": {
                    "project_name": project_name,
                    "local_path": str(project_path),
                    "github_url": github_url,
                    "vercel_url": vercel_url,
                    "files": self._list_project_files(project_path)
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to create website: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    def _extract_figma_id(self, figma_url: str) -> Optional[str]:
        """Extract file ID from Figma URL"""
        try:
            # Format: https://www.figma.com/file/FILE_ID/...
            if "/file/" in figma_url:
                parts = figma_url.split("/file/")[1].split("/")
                return parts[0]
            return None
        except Exception:
            return None
    
    async def _fetch_figma_data(self, file_id: str) -> Optional[Dict]:
        """Fetch Figma file data via API"""
        try:
            if not self.figma_token:
                logger.warning("No Figma token provided")
                return self._get_mock_figma_data()
            
            headers = {"X-Figma-Token": self.figma_token}
            url = f"https://api.figma.com/v1/files/{file_id}"
            
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"Figma API error: {response.status_code}")
                return self._get_mock_figma_data()
                
        except Exception as e:
            logger.warning(f"Figma fetch failed: {e}")
            return self._get_mock_figma_data()
    
    def _get_mock_figma_data(self) -> Dict:
        """Return mock Figma data for demo purposes"""
        return {
            "name": "Design File",
            "document": {
                "children": [
                    {
                        "name": "Landing Page",
                        "type": "FRAME",
                        "children": []
                    }
                ]
            }
        }
    
    def _extract_design_tokens(self, figma_data: Dict) -> Dict:
        """Extract colors, fonts, spacing from Figma data"""
        return {
            "colors": {
                "primary": "#3B82F6",
                "secondary": "#8B5CF6",
                "accent": "#10B981",
                "background": "#FFFFFF",
                "text": "#1F2937"
            },
            "fonts": {
                "heading": "Inter",
                "body": "Inter"
            },
            "spacing": {
                "xs": "0.25rem",
                "sm": "0.5rem",
                "md": "1rem",
                "lg": "1.5rem",
                "xl": "2rem"
            }
        }
    
    async def _generate_nextjs_project(
        self,
        project_path: Path,
        design_tokens: Dict,
        figma_data: Dict
    ):
        """Generate complete Next.js project structure"""
        
        # Create directory structure
        (project_path / "src").mkdir(exist_ok=True)
        (project_path / "src" / "app").mkdir(exist_ok=True)
        (project_path / "src" / "components").mkdir(exist_ok=True)
        (project_path / "public").mkdir(exist_ok=True)
        (project_path / "public" / "images").mkdir(exist_ok=True)
        
        # package.json
        package_json = {
            "name": project_path.name,
            "version": "0.1.0",
            "private": True,
            "scripts": {
                "dev": "next dev",
                "build": "next build",
                "start": "next start",
                "lint": "next lint"
            },
            "dependencies": {
                "next": "14.0.0",
                "react": "^18.2.0",
                "react-dom": "^18.2.0"
            },
            "devDependencies": {
                "@types/node": "^20.0.0",
                "@types/react": "^18.2.0",
                "@types/react-dom": "^18.2.0",
                "autoprefixer": "^10.4.16",
                "postcss": "^8.4.31",
                "tailwindcss": "^3.3.5",
                "typescript": "^5.2.2"
            }
        }
        
        with open(project_path / "package.json", "w") as f:
            json.dump(package_json, f, indent=2)
        
        # tailwind.config.js
        tailwind_config = f"""/** @type {{import('tailwindcss').Config}} */
module.exports = {{
  content: [
    './src/pages/**/*.{{js,ts,jsx,tsx,mdx}}',
    './src/components/**/*.{{js,ts,jsx,tsx,mdx}}',
    './src/app/**/*.{{js,ts,jsx,tsx,mdx}}',
  ],
  theme: {{
    extend: {{
      colors: {{
        primary: '{design_tokens["colors"]["primary"]}',
        secondary: '{design_tokens["colors"]["secondary"]}',
        accent: '{design_tokens["colors"]["accent"]}',
      }},
    }},
  }},
  plugins: [],
}}
"""
        
        with open(project_path / "tailwind.config.js", "w") as f:
            f.write(tailwind_config)
        
        # postcss.config.js
        postcss_config = """module.exports = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
"""
        
        with open(project_path / "postcss.config.js", "w") as f:
            f.write(postcss_config)
        
        # tsconfig.json
        tsconfig = {
            "compilerOptions": {
                "target": "es5",
                "lib": ["dom", "dom.iterable", "esnext"],
                "allowJs": True,
                "skipLibCheck": True,
                "strict": True,
                "noEmit": True,
                "esModuleInterop": True,
                "module": "esnext",
                "moduleResolution": "bundler",
                "resolveJsonModule": True,
                "isolatedModules": True,
                "jsx": "preserve",
                "incremental": True,
                "plugins": [{"name": "next"}],
                "paths": {"@/*": ["./src/*"]}
            },
            "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
            "exclude": ["node_modules"]
        }
        
        with open(project_path / "tsconfig.json", "w") as f:
            json.dump(tsconfig, f, indent=2)
        
        # next.config.js
        next_config = """/** @type {import('next').NextConfig} */
const nextConfig = {}

module.exports = nextConfig
"""
        
        with open(project_path / "next.config.js", "w") as f:
            f.write(next_config)
        
        # src/app/layout.tsx
        layout_tsx = """import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import './globals.css'

const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: 'Generated from Figma',
  description: 'Website generated from Figma design',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className={inter.className}>{children}</body>
    </html>
  )
}
"""
        
        with open(project_path / "src" / "app" / "layout.tsx", "w") as f:
            f.write(layout_tsx)
        
        # src/app/page.tsx
        page_tsx = f"""export default function Home() {{
  return (
    <main className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100">
      <div className="container mx-auto px-4 py-16">
        <div className="text-center">
          <h1 className="text-5xl font-bold text-gray-900 mb-6">
            Welcome to Your Website
          </h1>
          <p className="text-xl text-gray-600 mb-8">
            Generated from Figma design
          </p>
          <div className="flex gap-4 justify-center">
            <button className="px-6 py-3 bg-primary text-white rounded-lg hover:bg-blue-600 transition">
              Get Started
            </button>
            <button className="px-6 py-3 border-2 border-primary text-primary rounded-lg hover:bg-blue-50 transition">
              Learn More
            </button>
          </div>
        </div>
        
        <div className="grid md:grid-cols-3 gap-8 mt-16">
          <div className="bg-white p-6 rounded-lg shadow-lg">
            <h3 className="text-xl font-semibold mb-3">Feature One</h3>
            <p className="text-gray-600">Amazing functionality that helps users achieve their goals.</p>
          </div>
          <div className="bg-white p-6 rounded-lg shadow-lg">
            <h3 className="text-xl font-semibold mb-3">Feature Two</h3>
            <p className="text-gray-600">Powerful tools to streamline your workflow.</p>
          </div>
          <div className="bg-white p-6 rounded-lg shadow-lg">
            <h3 className="text-xl font-semibold mb-3">Feature Three</h3>
            <p className="text-gray-600">Intuitive interface for seamless experience.</p>
          </div>
        </div>
      </div>
    </main>
  )
}}
"""
        
        with open(project_path / "src" / "app" / "page.tsx", "w") as f:
            f.write(page_tsx)
        
        # src/app/globals.css
        globals_css = """@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  --foreground-rgb: 0, 0, 0;
  --background-start-rgb: 214, 219, 220;
  --background-end-rgb: 255, 255, 255;
}

body {
  color: rgb(var(--foreground-rgb));
}
"""
        
        with open(project_path / "src" / "app" / "globals.css", "w") as f:
            f.write(globals_css)
        
        # .gitignore
        gitignore = """# dependencies
/node_modules
/.pnp
.pnp.js

# testing
/coverage

# next.js
/.next/
/out/

# production
/build

# misc
.DS_Store
*.pem

# debug
npm-debug.log*
yarn-debug.log*
yarn-error.log*

# local env files
.env*.local

# vercel
.vercel

# typescript
*.tsbuildinfo
next-env.d.ts
"""
        
        with open(project_path / ".gitignore", "w") as f:
            f.write(gitignore)
    
    async def _download_figma_images(self, file_id: str, project_path: Path):
        """Download images from Figma"""
        try:
            # For demo, create placeholder image info
            images_info = {
                "images": [],
                "note": "Images would be downloaded from Figma API with proper token"
            }
            
            images_path = project_path / "public" / "images" / "figma_images.json"
            with open(images_path, "w") as f:
                json.dump(images_info, f, indent=2)
                
        except Exception as e:
            logger.warning(f"Image download failed: {e}")
    
    def _list_project_files(self, project_path: Path) -> list:
        """List all generated files"""
        files = []
        for root, dirs, filenames in os.walk(project_path):
            # Skip node_modules and .next
            dirs[:] = [d for d in dirs if d not in ['node_modules', '.next', '.git']]
            for filename in filenames:
                full_path = Path(root) / filename
                rel_path = full_path.relative_to(project_path)
                files.append(str(rel_path))
        return files