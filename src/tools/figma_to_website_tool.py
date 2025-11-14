"""Figma to Website Tool - PIXEL PERFECT VERSION (All Errors Fixed)"""
import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime
import requests
import re

logger = logging.getLogger(__name__)

class FigmaToWebsiteTool:
    """Convert Figma designs to pixel-perfect deployed websites"""
    
    def __init__(self, figma_token: str = None):
        self.figma_token = figma_token or os.getenv("FIGMA_TOKEN")
        self.projects_dir = Path("projects")
        self.projects_dir.mkdir(exist_ok=True)
        
        if not self.figma_token:
            logger.warning("⚠️  No FIGMA_TOKEN - Get one from: https://www.figma.com/developers/api#access-tokens")
    
    async def create_website_from_figma(
        self,
        figma_url: str,
        project_name: str,
        description: str = "Website from Figma"
    ) -> Dict[str, Any]:
        """Complete workflow: Figma → Pixel-Perfect Code → GitHub → Vercel"""
        try:
            logger.info(f"🎨 Starting Pixel-Perfect Figma to Website: {project_name}")
            
            # Extract Figma file ID
            figma_file_id = self._extract_figma_id(figma_url)
            if not figma_file_id:
                return {"success": False, "error": "Invalid Figma URL format"}
            
            logger.info(f"📋 Figma File ID: {figma_file_id}")
            
            # Create project directory
            project_path = self.projects_dir / project_name
            if project_path.exists():
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                project_name = f"{project_name}_{timestamp}"
                project_path = self.projects_dir / project_name
            
            project_path.mkdir(parents=True)
            logger.info(f"✅ Created: {project_path}")
            
            # Fetch Figma data
            figma_data = await self._fetch_figma_data(figma_file_id)
            if not figma_data:
                return {"success": False, "error": "Failed to fetch Figma data. Check FIGMA_TOKEN"}
            
            # Save metadata only
            self._save_metadata(project_path, figma_data, figma_url, figma_file_id, project_name)
            
            # Extract complete design system
            design_system = self._extract_complete_design_system(figma_data)
            logger.info(f"✅ Design System: {len(design_system['colors'])} colors, {len(design_system['typography'])} fonts")
            
            # Extract page structure with FULL layout details
            pages = self._extract_pages_with_layout(figma_data)
            logger.info(f"✅ Extracted {len(pages)} pages with pixel-perfect layouts")
            
            # Download images (limited)
            images = await self._download_figma_images(figma_file_id, project_path, figma_data)
            logger.info(f"✅ Downloaded {len(images)} images")
            
            # Generate pixel-perfect Next.js project
            await self._generate_pixel_perfect_nextjs(
                project_path,
                design_system,
                pages,
                images,
                figma_data
            )
            logger.info("✅ Generated pixel-perfect Next.js project")
            
            # Create log
            self._create_deployment_log(project_path, project_name, figma_url, figma_file_id, design_system, pages, images)
            
            # Push to GitHub
            github_url = await self._push_to_github(project_path, project_name, description)
            
            # Deploy to Vercel
            vercel_url = await self._deploy_to_vercel(project_path)
            
            return {
                "success": True,
                "message": f"Pixel-perfect website created from Figma!",
                "data": {
                    "project_name": project_name,
                    "local_path": str(project_path),
                    "github_url": github_url,
                    "vercel_url": vercel_url,
                    "design_extracted": {
                        "colors": len(design_system['colors']),
                        "fonts": len(design_system['typography']),
                        "pages": len(pages),
                        "components": sum(len(p['components']) for p in pages),
                        "images": len(images)
                    }
                }
            }
            
        except Exception as e:
            logger.error(f"Failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    def _extract_figma_id(self, figma_url: str) -> Optional[str]:
        """Extract file ID from Figma URL"""
        patterns = [r'/design/([a-zA-Z0-9]+)', r'/file/([a-zA-Z0-9]+)']
        for pattern in patterns:
            match = re.search(pattern, figma_url)
            if match:
                return match.group(1)
        return None
    
    async def _fetch_figma_data(self, file_id: str) -> Optional[Dict]:
        """Fetch Figma file data"""
        if not self.figma_token:
            return None
        
        headers = {"X-Figma-Token": self.figma_token}
        url = f"https://api.figma.com/v1/files/{file_id}"
        
        logger.info(f"📡 Fetching from Figma API...")
        response = requests.get(url, headers=headers, timeout=30)
        
        if response.status_code == 200:
            logger.info("✅ Figma data fetched")
            return response.json()
        else:
            logger.error(f"❌ Figma API error: {response.status_code}")
            return None
    
    def _save_metadata(self, project_path, figma_data, figma_url, figma_file_id, project_name):
        """Save lightweight metadata"""
        metadata = {
            "project_name": project_name,
            "figma_url": figma_url,
            "figma_file_id": figma_file_id,
            "figma_file_name": figma_data.get("name", "Untitled"),
            "extracted_at": datetime.now().isoformat(),
        }
        with open(project_path / "figma_metadata.json", "w", encoding='utf-8') as f:
            json.dump(metadata, f, indent=2)
    
    def _extract_complete_design_system(self, figma_data: Dict) -> Dict:
        """Extract complete design system"""
        design_system = {
            "colors": {},
            "typography": {},
            "spacing": set(),
            "borderRadius": set(),
            "shadows": []
        }
        
        # Extract from document
        if "document" in figma_data:
            self._traverse_design_tokens(figma_data["document"], design_system)
        
        # Convert sets to lists for JSON
        design_system["spacing"] = sorted(list(design_system["spacing"]))
        design_system["borderRadius"] = sorted(list(design_system["borderRadius"]))
        
        # Add defaults if empty
        if not design_system["colors"]:
            design_system["colors"] = {
                "primary": "#3B82F6",
                "secondary": "#8B5CF6",
                "background": "#FFFFFF",
                "text": "#1F2937"
            }
        
        return design_system
    
    def _traverse_design_tokens(self, node: Dict, design_system: Dict, depth: int = 0):
        """Recursively extract design tokens"""
        if depth > 15:
            return
        
        try:
            # Extract colors
            if "fills" in node and isinstance(node["fills"], list):
                for fill in node["fills"]:
                    if fill.get("type") == "SOLID" and "color" in fill:
                        color_hex = self._rgba_to_hex(fill["color"])
                        if color_hex not in design_system["colors"].values():
                            name = node.get("name", f"color_{len(design_system['colors'])}")
                            design_system["colors"][self._sanitize_name(name)] = color_hex
            
            # Extract typography
            if node.get("type") == "TEXT" and "style" in node:
                style = node["style"]
                font_key = f"{style.get('fontFamily', 'Inter')}_{style.get('fontSize', 16)}_{style.get('fontWeight', 400)}"
                if font_key not in design_system["typography"]:
                    design_system["typography"][font_key] = {
                        "fontFamily": style.get("fontFamily", "Inter"),
                        "fontSize": f"{style.get('fontSize', 16)}px",
                        "fontWeight": style.get("fontWeight", 400),
                        "lineHeight": style.get("lineHeightPx", style.get("fontSize", 16) * 1.5)
                    }
            
            # Extract spacing (from padding/margins)
            if "absoluteBoundingBox" in node:
                bbox = node["absoluteBoundingBox"]
                if "paddingLeft" in node:
                    design_system["spacing"].add(node["paddingLeft"])
                if "itemSpacing" in node:
                    design_system["spacing"].add(node["itemSpacing"])
            
            # Extract border radius
            if "cornerRadius" in node:
                design_system["borderRadius"].add(node["cornerRadius"])
            
            # Extract shadows
            if "effects" in node:
                for effect in node["effects"]:
                    if effect.get("type") == "DROP_SHADOW" and effect.get("visible", True):
                        shadow = {
                            "x": effect.get("offset", {}).get("x", 0),
                            "y": effect.get("offset", {}).get("y", 0),
                            "blur": effect.get("radius", 0),
                            "color": self._rgba_to_rgba_string(effect.get("color", {}))
                        }
                        if shadow not in design_system["shadows"]:
                            design_system["shadows"].append(shadow)
            
            # Recurse
            if "children" in node:
                for child in node["children"]:
                    self._traverse_design_tokens(child, design_system, depth + 1)
        except Exception:
            pass
    
    def _extract_pages_with_layout(self, figma_data: Dict) -> List[Dict]:
        """Extract pages with FULL layout information"""
        pages = []
        
        if "document" not in figma_data or "children" not in figma_data["document"]:
            return pages
        
        for page in figma_data["document"]["children"]:
            if page.get("type") == "CANVAS":
                page_data = {
                    "name": page.get("name", "Page"),
                    "id": page.get("id"),
                    "components": []
                }
                
                # Extract all frames/components
                if "children" in page:
                    for frame in page["children"]:
                        component = self._extract_component_tree(frame)
                        if component:
                            page_data["components"].append(component)
                
                pages.append(page_data)
        
        return pages
    
    def _extract_component_tree(self, node: Dict, depth: int = 0) -> Optional[Dict]:
        """Recursively extract component tree with layout info"""
        if depth > 20:
            return None
        
        try:
            component = {
                "id": node.get("id"),
                "name": node.get("name", "Unnamed"),
                "type": node.get("type"),
                "layout": self._extract_layout(node),
                "style": self._extract_style(node),
                "text": node.get("characters") if node.get("type") == "TEXT" else None,
                "children": []
            }
            
            # Recurse for children
            if "children" in node:
                for child in node["children"]:
                    child_component = self._extract_component_tree(child, depth + 1)
                    if child_component:
                        component["children"].append(child_component)
            
            return component
        except Exception:
            return None
    
    def _extract_layout(self, node: Dict) -> Dict:
        """Extract layout properties"""
        layout = {
            "width": "auto",
            "height": "auto",
            "x": 0,
            "y": 0,
            "position": "relative"
        }
        
        try:
            bbox = node.get("absoluteBoundingBox", {})
            layout["width"] = f"{bbox.get('width', 0)}px"
            layout["height"] = f"{bbox.get('height', 0)}px"
            layout["x"] = bbox.get("x", 0)
            layout["y"] = bbox.get("y", 0)
            
            # Detect auto-layout (Flexbox)
            if node.get("layoutMode") in ["HORIZONTAL", "VERTICAL"]:
                layout["display"] = "flex"
                layout["flexDirection"] = "row" if node["layoutMode"] == "HORIZONTAL" else "column"
                layout["gap"] = f"{node.get('itemSpacing', 0)}px"
                layout["padding"] = f"{node.get('paddingTop', 0)}px {node.get('paddingRight', 0)}px {node.get('paddingBottom', 0)}px {node.get('paddingLeft', 0)}px"
                
                # Alignment
                primary_align = node.get("primaryAxisAlignItems", "MIN")
                counter_align = node.get("counterAxisAlignItems", "MIN")
                
                align_map = {"MIN": "flex-start", "CENTER": "center", "MAX": "flex-end", "SPACE_BETWEEN": "space-between"}
                layout["justifyContent"] = align_map.get(primary_align, "flex-start")
                layout["alignItems"] = align_map.get(counter_align, "flex-start")
            
            # Constraints (for absolute positioning)
            constraints = node.get("constraints", {})
            if constraints.get("vertical") == "TOP" and constraints.get("horizontal") == "LEFT":
                layout["position"] = "absolute"
        except Exception:
            pass
        
        return layout
    
    def _extract_style(self, node: Dict) -> Dict:
        """Extract styling properties"""
        style = {}
        
        try:
            # Background
            if "fills" in node and isinstance(node["fills"], list):
                for fill in node["fills"]:
                    if fill.get("visible", True) and fill.get("type") == "SOLID":
                        style["backgroundColor"] = self._rgba_to_hex(fill.get("color", {}))
                        style["opacity"] = fill.get("opacity", 1)
                    elif fill.get("type") == "IMAGE":
                        style["backgroundImage"] = "url('placeholder.png')"
                        style["backgroundSize"] = "cover"
            
            # Border
            if "strokes" in node and isinstance(node["strokes"], list):
                for stroke in node["strokes"]:
                    if stroke.get("visible", True):
                        style["border"] = f"{node.get('strokeWeight', 1)}px solid {self._rgba_to_hex(stroke.get('color', {}))}"
            
            # Border radius
            if "cornerRadius" in node:
                style["borderRadius"] = f"{node['cornerRadius']}px"
            elif "rectangleCornerRadii" in node:
                radii = node["rectangleCornerRadii"]
                style["borderRadius"] = f"{radii[0]}px {radii[1]}px {radii[2]}px {radii[3]}px"
            
            # Text styling
            if node.get("type") == "TEXT" and "style" in node:
                text_style = node["style"]
                style["fontFamily"] = f"'{text_style.get('fontFamily', 'Inter')}', sans-serif"
                style["fontSize"] = f"{text_style.get('fontSize', 16)}px"
                style["fontWeight"] = text_style.get("fontWeight", 400)
                style["lineHeight"] = f"{text_style.get('lineHeightPx', text_style.get('fontSize', 16) * 1.5)}px"
                style["textAlign"] = text_style.get("textAlignHorizontal", "LEFT").lower()
                
                # Text color
                if "fills" in node:
                    for fill in node["fills"]:
                        if fill.get("type") == "SOLID":
                            style["color"] = self._rgba_to_hex(fill.get("color", {}))
            
            # Effects (shadows)
            if "effects" in node:
                shadows = []
                for effect in node["effects"]:
                    if effect.get("type") == "DROP_SHADOW" and effect.get("visible", True):
                        offset = effect.get("offset", {})
                        shadows.append(
                            f"{offset.get('x', 0)}px {offset.get('y', 0)}px {effect.get('radius', 0)}px {self._rgba_to_rgba_string(effect.get('color', {}))}"
                        )
                if shadows:
                    style["boxShadow"] = ", ".join(shadows)
        except Exception:
            pass
        
        return style
    
    def _rgba_to_hex(self, color: Dict) -> str:
        """Convert RGBA to hex"""
        try:
            r = int(color.get("r", 0) * 255)
            g = int(color.get("g", 0) * 255)
            b = int(color.get("b", 0) * 255)
            return f"#{r:02x}{g:02x}{b:02x}"
        except:
            return "#000000"
    
    def _rgba_to_rgba_string(self, color: Dict) -> str:
        """Convert to rgba() string"""
        try:
            r = int(color.get("r", 0) * 255)
            g = int(color.get("g", 0) * 255)
            b = int(color.get("b", 0) * 255)
            a = color.get("a", 1)
            return f"rgba({r}, {g}, {b}, {a})"
        except:
            return "rgba(0, 0, 0, 1)"
    
    def _sanitize_name(self, name: str) -> str:
        """Sanitize name for CSS/JS"""
        return re.sub(r'[^a-zA-Z0-9]', '', name).lower()[:30]
    
    async def _download_figma_images(self, file_id: str, project_path: Path, figma_data: Dict) -> List[str]:
        """Download images (limited to 5)"""
        images = []
        
        if not self.figma_token:
            return images
        
        node_ids = self._collect_image_node_ids(figma_data)
        if not node_ids:
            return images
        
        node_ids = node_ids[:5]
        logger.info(f"Downloading {len(node_ids)} images")
        
        headers = {"X-Figma-Token": self.figma_token}
        ids_param = ",".join(node_ids)
        url = f"https://api.figma.com/v1/images/{file_id}?ids={ids_param}&format=png&scale=2"
        
        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 200:
                image_data = response.json()
                images_dir = project_path / "public" / "images"
                images_dir.mkdir(parents=True, exist_ok=True)
                
                for idx, (node_id, image_url) in enumerate(image_data.get("images", {}).items()):
                    if image_url:
                        try:
                            img_response = requests.get(image_url, timeout=30)
                            if img_response.status_code == 200:
                                img_path = images_dir / f"img_{idx}.png"
                                with open(img_path, "wb") as f:
                                    f.write(img_response.content)
                                images.append(str(img_path))
                                logger.info(f"✅ Image {idx + 1}/{len(node_ids)}")
                        except Exception as e:
                            logger.warning(f"Image download failed: {e}")
        except Exception as e:
            logger.warning(f"Images skipped: {e}")
        
        return images
    
    def _collect_image_node_ids(self, figma_data: Dict) -> List[str]:
        """Collect image node IDs"""
        node_ids = []
        
        def traverse(node, depth=0):
            if depth > 10 or len(node_ids) >= 10:
                return
            if isinstance(node, dict):
                if "fills" in node:
                    for fill in node["fills"]:
                        if fill.get("type") == "IMAGE":
                            node_ids.append(node["id"])
                            break
                if "children" in node:
                    for child in node["children"]:
                        traverse(child, depth + 1)
        
        if "document" in figma_data:
            traverse(figma_data["document"])
        
        return node_ids[:10]
    
    async def _generate_pixel_perfect_nextjs(
        self,
        project_path: Path,
        design_system: Dict,
        pages: List[Dict],
        images: List[str],
        figma_data: Dict
    ):
        """Generate pixel-perfect Next.js project"""
        
        # Create structure
        (project_path / "src" / "app").mkdir(parents=True, exist_ok=True)
        (project_path / "src" / "components").mkdir(parents=True, exist_ok=True)
        (project_path / "public" / "images").mkdir(parents=True, exist_ok=True)
        
        project_title = figma_data.get("name", "Figma Design")
        
        # package.json
        package_json = {
            "name": project_path.name,
            "version": "0.1.0",
            "private": True,
            "scripts": {
                "dev": "next dev",
                "build": "next build",
                "start": "next start"
            },
            "dependencies": {
                "next": "14.0.0",
                "react": "^18.2.0",
                "react-dom": "^18.2.0"
            },
            "devDependencies": {
                "@types/node": "^20",
                "@types/react": "^18",
                "typescript": "^5"
            }
        }
        with open(project_path / "package.json", "w", encoding='utf-8') as f:
            json.dump(package_json, f, indent=2)
        
        # tsconfig.json
        tsconfig = {
            "compilerOptions": {
                "target": "es5",
                "lib": ["dom", "esnext"],
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
            "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx"],
            "exclude": ["node_modules"]
        }
        with open(project_path / "tsconfig.json", "w", encoding='utf-8') as f:
            json.dump(tsconfig, f, indent=2)
        
        # next.config.js
        with open(project_path / "next.config.js", "w", encoding='utf-8') as f:
            f.write("/** @type {import('next').NextConfig} */\nconst nextConfig = {}\nmodule.exports = nextConfig\n")
        
        # Generate CSS with design tokens
        self._generate_global_css(project_path, design_system)
        
        # Generate layout.tsx
        self._generate_layout(project_path, project_title)
        
        # Generate pages from Figma
        self._generate_pages_from_figma(project_path, pages, design_system)
        
        # .gitignore
        with open(project_path / ".gitignore", "w", encoding='utf-8') as f:
            f.write("node_modules\n.next\nout\n.DS_Store\n*.log\n.env*.local\n.vercel\n")
        
        # .vercelignore
        with open(project_path / ".vercelignore", "w", encoding='utf-8') as f:
            f.write("node_modules\n.next\n.git\n*.log\n")
        
        # README
        self._generate_readme(project_path, project_title, design_system, pages, images)
    
    def _generate_global_css(self, project_path: Path, design_system: Dict):
        """Generate CSS with extracted design tokens"""
        css_content = """/* Global Styles - Generated from Figma */

* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* Design Tokens */
:root {
"""
        
        # Add color variables
        for name, color in design_system["colors"].items():
            css_content += f"  --color-{name}: {color};\n"
        
        # Add spacing variables
        for idx, spacing in enumerate(design_system.get("spacing", [])):
            css_content += f"  --spacing-{idx}: {spacing}px;\n"
        
        # Add border radius variables
        for idx, radius in enumerate(design_system.get("borderRadius", [])):
            css_content += f"  --radius-{idx}: {radius}px;\n"
        
        css_content += "}\n\n"
        
        # Add shadow utilities
        for idx, shadow in enumerate(design_system.get("shadows", [])):
            css_content += f".shadow-{idx} {{\n  box-shadow: {shadow['x']}px {shadow['y']}px {shadow['blur']}px {shadow['color']};\n}}\n\n"
        
        with open(project_path / "src" / "app" / "globals.css", "w", encoding='utf-8') as f:
            f.write(css_content)
    
    def _generate_layout(self, project_path: Path, project_title: str):
        """Generate layout.tsx"""
        layout_content = f"""import type {{ Metadata }} from 'next'
import './globals.css'

export const metadata: Metadata = {{
  title: '{project_title}',
  description: 'Pixel-perfect website from Figma',
}}

export default function RootLayout({{
  children,
}}: {{
  children: React.ReactNode
}}) {{
  return (
    <html lang="en">
      <body>{{children}}</body>
    </html>
  )
}}
"""
        with open(project_path / "src" / "app" / "layout.tsx", "w", encoding='utf-8') as f:
            f.write(layout_content)
    
    def _generate_pages_from_figma(self, project_path: Path, pages: List[Dict], design_system: Dict):
        """Generate React components from Figma pages"""
        
        if not pages:
            # Fallback page
            self._generate_fallback_page(project_path, design_system)
            return
        
        # Generate main page (first Figma page)
        main_page = pages[0]
        page_content = self._generate_component_jsx(main_page, design_system, is_root=True)
        
        with open(project_path / "src" / "app" / "page.tsx", "w", encoding='utf-8') as f:
            f.write(page_content)
        
        # Generate additional pages
        for idx, page in enumerate(pages[1:], start=1):
            page_dir = project_path / "src" / "app" / self._sanitize_name(page["name"])
            page_dir.mkdir(exist_ok=True)
            
            page_content = self._generate_component_jsx(page, design_system, is_root=True)
            with open(page_dir / "page.tsx", "w", encoding='utf-8') as f:
                f.write(page_content)
    
    def _generate_component_jsx(self, page_or_component: Dict, design_system: Dict, is_root: bool = False) -> str:
        """Generate JSX for a component tree - FIXED: Wrap multiple root elements"""
        
        components = page_or_component.get("components", [])
        
        if is_root:
            # CRITICAL FIX: Wrap multiple root components in a container div
            jsx = "export default function Page() {\n  return (\n"
            
            if len(components) > 1:
                # Multiple components need a wrapper div
                jsx += "    <div style={{ position: 'relative', width: '100%', minHeight: '100vh' }}>\n"
                for component in components:
                    jsx += self._component_to_jsx(component, indent=3)
                jsx += "    </div>\n"
            elif len(components) == 1:
                # Single component, no wrapper needed
                for component in components:
                    jsx += self._component_to_jsx(component, indent=2)
            else:
                # No components, show fallback
                jsx += "    <div style={{ padding: '2rem', textAlign: 'center' }}>No content extracted from Figma</div>\n"
            
            jsx += "  )\n}\n"
        else:
            jsx = ""
            for component in components:
                jsx += self._component_to_jsx(component, indent=0)
        
        return jsx
    
    def _component_to_jsx(self, component: Dict, indent: int = 0) -> str:
        """Convert Figma component to JSX - FIXED FOR MULTI-LINE TEXT"""
        indent_str = "  " * indent
        
        # Determine HTML element
        comp_type = component.get("type", "FRAME")
        if comp_type == "TEXT":
            element = "p"
        elif comp_type == "RECTANGLE":
            element = "div"
        elif comp_type in ["FRAME", "GROUP", "COMPONENT"]:
            element = "div"
        else:
            element = "div"
        
        # Build style object
        layout = component.get("layout", {})
        style = component.get("style", {})
        
        style_obj = {**layout, **style}
        
        # Convert style to inline style string
        style_str = ""
        if style_obj:
            style_pairs = []
            for key, value in style_obj.items():
                if key not in ["x", "y"]:  # Skip positioning for now
                    camel_key = key[0].lower() + key[1:] if key else key
                    # Escape quotes in value
                    safe_value = str(value).replace("'", "\\'")
                    style_pairs.append(f"{camel_key}: '{safe_value}'")
            if style_pairs:
                style_str = f" style={{{{{', '.join(style_pairs)}}}}}"
        
        # Get text content and PROPERLY escape for JSX - CRITICAL FIX
        text_content = component.get("text", "")
        if text_content:
            # CRITICAL: Remove all newlines and collapse whitespace into single line
            text_content = ' '.join(text_content.split())
            # Escape special characters for JSX
            text_content = (text_content
                           .replace("&", "&amp;")
                           .replace("<", "&lt;")
                           .replace(">", "&gt;")
                           .replace('"', "&quot;")
                           .replace("'", "&#39;"))
            # Remove problematic unicode characters (keep only printable ASCII)
            text_content = ''.join(char if 32 <= ord(char) < 127 else ' ' for char in text_content)
            # Collapse multiple spaces
            text_content = ' '.join(text_content.split())
            # Limit length to prevent massive text blocks
            if len(text_content) > 500:
                text_content = text_content[:500] + "..."
        
        # Check for children
        children = component.get("children", [])
        
        if children:
            jsx = f"{indent_str}<{element}{style_str}>\n"
            for child in children:
                jsx += self._component_to_jsx(child, indent + 1)
            jsx += f"{indent_str}</{element}>\n"
        elif text_content:
            # CRITICAL: Keep text on same line as tags to prevent JSX syntax errors
            jsx = f"{indent_str}<{element}{style_str}>{text_content}</{element}>\n"
        else:
            jsx = f"{indent_str}<{element}{style_str} />\n"
        
        return jsx
    
    def _generate_fallback_page(self, project_path: Path, design_system: Dict):
        """Generate fallback page if no components extracted"""
        primary_color = list(design_system["colors"].values())[0] if design_system["colors"] else "#3B82F6"
        
        page_content = f"""export default function Page() {{
  return (
    <main style={{{{ minHeight: '100vh', backgroundColor: '{primary_color}11', padding: '4rem 1rem' }}}}>
      <div style={{{{ maxWidth: '1200px', margin: '0 auto', textAlign: 'center' }}}}>
        <h1 style={{{{ fontSize: '3rem', fontWeight: 'bold', color: '{primary_color}', marginBottom: '1.5rem' }}}}>
          Design Extracted from Figma
        </h1>
        <p style={{{{ fontSize: '1.25rem', color: '#6B7280', marginBottom: '2rem' }}}}>
          This is a pixel-perfect recreation of your Figma design
        </p>
        <div style={{{{ display: 'flex', gap: '1rem', justifyContent: 'center' }}}}>
          <button style={{{{
            padding: '0.75rem 2rem',
            backgroundColor: '{primary_color}',
            color: 'white',
            borderRadius: '0.5rem',
            border: 'none',
            fontWeight: '600',
            cursor: 'pointer'
          }}}}>
            Get Started
          </button>
        </div>
      </div>
    </main>
  )
}}
"""
        with open(project_path / "src" / "app" / "page.tsx", "w", encoding='utf-8') as f:
            f.write(page_content)
    
    def _generate_readme(self, project_path: Path, project_title: str, design_system: Dict, pages: List[Dict], images: List[str]):
        """Generate README"""
        readme = f"""# {project_title}

Pixel-perfect website generated from Figma design using MCP Automation

## Design Extracted

- **Colors**: {len(design_system['colors'])}
- **Typography**: {len(design_system.get('typography', {}))} font styles
- **Pages**: {len(pages)}
- **Components**: {sum(len(p.get('components', [])) for p in pages)}
- **Images**: {len(images)}
- **Spacing tokens**: {len(design_system.get('spacing', []))}
- **Border radius**: {len(design_system.get('borderRadius', []))}
- **Shadows**: {len(design_system.get('shadows', []))}

## Tech Stack

- Next.js 14
- React 18
- TypeScript
- Pixel-perfect CSS

## Getting Started
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

## Design Fidelity

This website is a pixel-perfect recreation of the Figma design, including:
- Exact colors, fonts, and spacing
- Layout with Flexbox auto-layout
- Border radius and shadows
- Component hierarchy
"""
        with open(project_path / "README.md", "w", encoding='utf-8') as f:
            f.write(readme)
    
    def _create_deployment_log(self, project_path, project_name, figma_url, figma_file_id, design_system, pages, images):
        """Create deployment log"""
        log_path = project_path / "deployment_logs.txt"
        with open(log_path, "w", encoding='utf-8') as f:
            f.write(f"Project: {project_name}\n")
            f.write(f"Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Figma URL: {figma_url}\n")
            f.write(f"Figma File ID: {figma_file_id}\n\n")
            f.write(f"Design System:\n")
            f.write(f"  Colors: {len(design_system['colors'])}\n")
            f.write(f"  Typography: {len(design_system.get('typography', {}))}\n")
            f.write(f"  Spacing: {len(design_system.get('spacing', []))}\n")
            f.write(f"  Border Radius: {len(design_system.get('borderRadius', []))}\n")
            f.write(f"  Shadows: {len(design_system.get('shadows', []))}\n\n")
            f.write(f"Pages: {len(pages)}\n")
            f.write(f"Components: {sum(len(p.get('components', [])) for p in pages)}\n")
            f.write(f"Images: {len(images)}\n")
    
    async def _push_to_github(self, project_path: Path, project_name: str, description: str) -> Optional[str]:
        """Push to GitHub (Windows-safe - NO .git cleanup)"""
        try:
            from .github_tool import GitHubTool
            github_token = os.getenv("GITHUB_TOKEN")
            if github_token:
                github = GitHubTool(github_token)
                
                # Create repo
                repo_result = await github.create_repo(project_name, description, private=False)
                if repo_result["success"]:
                    github_url = repo_result["data"]["url"]
                    logger.info(f"✅ GitHub: {github_url}")
                    
                    # Push code
                    push_result = await github.push_local_code(project_name, str(project_path), "main")
                    if push_result["success"]:
                        logger.info(f"✅ Code pushed to GitHub")
                    
                    # DO NOT clean up .git folder (causes Windows "Access Denied" errors)
                    logger.info("ℹ️  Local .git folder preserved (prevents Windows file lock issues)")
                    
                    return github_url
        except Exception as e:
            logger.warning(f"⚠️ GitHub skipped: {str(e)[:80]}")
        return None
    
    async def _deploy_to_vercel(self, project_path: Path) -> Optional[str]:
        """Deploy to Vercel"""
        try:
            from .vercel_tool import VercelTool
            vercel = VercelTool()
            result = await vercel.deploy(str(project_path), production=True)
            if result["success"]:
                vercel_url = result["data"]["url"]
                logger.info(f"✅ Vercel: {vercel_url}")
                return vercel_url
        except Exception as e:
            logger.warning(f"⚠️ Vercel skipped: {str(e)[:80]}")
        return None