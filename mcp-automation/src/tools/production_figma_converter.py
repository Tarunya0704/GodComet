"""
PRODUCTION-GRADE FIGMA TO CODE CONVERTER
Handles: Auto-layout, Components, Responsive, Images, Tailwind, Component extraction
UPDATED: Added caching + auto-retry for rate limit handling
"""
import os
import json
import requests
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import logging
from urllib.parse import urlparse
import asyncio
import aiohttp
import time  # ⭐ ADDED for caching
import hashlib
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class FigmaNode:
    """Represents a Figma node with all its properties"""
    
    def __init__(self, data: Dict):
        self.raw = data
        self.id = data.get("id")
        self.name = data.get("name", "")
        self.type = data.get("type")
        self.visible = data.get("visible", True)
        self.children = [FigmaNode(c) for c in data.get("children", [])]
        
        # Layout properties
        self.absolute_bounds = data.get("absoluteBoundingBox", {})
        self.layout_mode = data.get("layoutMode", "NONE")  # AUTO-LAYOUT
        self.constraints = data.get("constraints", {})
        
        # Auto-layout properties
        self.primary_axis_align = data.get("primaryAxisAlignItems", "MIN")
        self.counter_axis_align = data.get("counterAxisAlignItems", "MIN")
        self.primary_axis_sizing = data.get("primaryAxisSizingMode", "AUTO")
        self.counter_axis_sizing = data.get("counterAxisSizingMode", "AUTO")
        self.padding = {
            "top": data.get("paddingTop", 0),
            "right": data.get("paddingRight", 0),
            "bottom": data.get("paddingBottom", 0),
            "left": data.get("paddingLeft", 0)
        }
        self.item_spacing = data.get("itemSpacing", 0)
        
        # Visual properties
        self.fills = data.get("fills", [])
        self.strokes = data.get("strokes", [])
        self.effects = data.get("effects", [])
        self.corner_radius = data.get("cornerRadius", 0)
        self.opacity = data.get("opacity", 1)
        
        # Text properties
        self.characters = data.get("characters", "")
        self.style = data.get("style", {})
        
        # Component properties
        self.component_id = data.get("componentId")
        self.is_component = self.type in ["COMPONENT", "COMPONENT_SET"]
        self.is_instance = self.type == "INSTANCE"
        
    @property
    def width(self):
        return self.absolute_bounds.get("width", 0)
    
    @property
    def height(self):
        return self.absolute_bounds.get("height", 0)
    
    @property
    def has_auto_layout(self):
        return self.layout_mode in ["HORIZONTAL", "VERTICAL"]


class ComponentExtractor:
    """Detects and extracts reusable components from Figma"""
    
    def __init__(self):
        self.components = {}  # id -> component definition
        self.instances = []   # list of component instances
        
    def extract(self, node: FigmaNode):
        """Recursively extract components"""
        # Store component definitions
        if node.is_component:
            self.components[node.id] = node
            logger.info(f"Found component: {node.name}")
        
        # Store component instances
        if node.is_instance and node.component_id:
            self.instances.append(node)
        
        # Recurse
        for child in node.children:
            self.extract(child)
    
    def get_component_usage(self) -> Dict[str, int]:
        """Count how many times each component is used"""
        usage = {}
        for instance in self.instances:
            comp_id = instance.component_id
            usage[comp_id] = usage.get(comp_id, 0) + 1
        return usage


class TailwindConverter:
    """Converts Figma styles to Tailwind CSS classes"""
    
    @staticmethod
    def get_layout_classes(node: FigmaNode) -> List[str]:
        """Convert auto-layout to Tailwind flex/grid classes"""
        classes = []
        
        if not node.has_auto_layout:
            return classes
        
        # Flex direction
        if node.layout_mode == "HORIZONTAL":
            classes.append("flex flex-row")
        elif node.layout_mode == "VERTICAL":
            classes.append("flex flex-col")
        
        # Justify content (primary axis)
        justify_map = {
            "MIN": "justify-start",
            "CENTER": "justify-center",
            "MAX": "justify-end",
            "SPACE_BETWEEN": "justify-between"
        }
        if node.primary_axis_align in justify_map:
            classes.append(justify_map[node.primary_axis_align])
        
        # Align items (counter axis)
        align_map = {
            "MIN": "items-start",
            "CENTER": "items-center",
            "MAX": "items-end",
            "BASELINE": "items-baseline"
        }
        if node.counter_axis_align in align_map:
            classes.append(align_map[node.counter_axis_align])
        
        # Gap (item spacing)
        gap = node.item_spacing
        if gap > 0:
            gap_class = TailwindConverter._size_to_tailwind(gap, "gap")
            classes.append(gap_class)
        
        return classes
    
    @staticmethod
    def get_spacing_classes(node: FigmaNode) -> List[str]:
        """Convert padding/margin to Tailwind"""
        classes = []
        
        p = node.padding
        # Check if all sides are equal
        if p["top"] == p["right"] == p["bottom"] == p["left"] and p["top"] > 0:
            classes.append(TailwindConverter._size_to_tailwind(p["top"], "p"))
        else:
            # Individual sides
            if p["top"] > 0:
                classes.append(TailwindConverter._size_to_tailwind(p["top"], "pt"))
            if p["right"] > 0:
                classes.append(TailwindConverter._size_to_tailwind(p["right"], "pr"))
            if p["bottom"] > 0:
                classes.append(TailwindConverter._size_to_tailwind(p["bottom"], "pb"))
            if p["left"] > 0:
                classes.append(TailwindConverter._size_to_tailwind(p["left"], "pl"))
        
        return classes
    
    @staticmethod
    def get_sizing_classes(node: FigmaNode) -> List[str]:
        """Convert width/height to Tailwind — respects auto-layout axis direction.

        In Figma:
          HORIZONTAL frame: primary axis = width, counter axis = height
          VERTICAL frame:   primary axis = height, counter axis = width
          No layout:        use actual absolute bounds directly
        """
        classes = []

        if node.layout_mode == "HORIZONTAL":
            # Primary → width
            if node.primary_axis_sizing == "FIXED":
                w = int(node.width)
                if w > 0:
                    classes.append(f"w-[{w}px]" if w <= 640 else "w-full")
            elif node.primary_axis_sizing == "FILL":
                classes.append("w-full")

            # Counter → height
            if node.counter_axis_sizing == "FIXED":
                h = int(node.height)
                if h > 0:
                    classes.append(f"h-[{h}px]")
            elif node.counter_axis_sizing == "FILL":
                classes.append("h-full")

        elif node.layout_mode == "VERTICAL":
            # Primary → height
            if node.primary_axis_sizing == "FIXED":
                h = int(node.height)
                if h > 0:
                    classes.append(f"h-[{h}px]")
            elif node.primary_axis_sizing == "FILL":
                classes.append("h-full")

            # Counter → width
            if node.counter_axis_sizing == "FIXED":
                w = int(node.width)
                if w > 0:
                    classes.append(f"w-[{w}px]" if w <= 640 else "w-full")
            elif node.counter_axis_sizing == "FILL":
                classes.append("w-full")

        else:
            # No auto-layout — size from absolute bounding box
            w = int(node.width)
            h = int(node.height)
            if w > 0:
                classes.append(f"w-[{w}px]" if w <= 640 else "w-full")
            if h > 0:
                classes.append(f"h-[{h}px]")

        return classes
    
    @staticmethod
    def get_color_classes(node: FigmaNode) -> List[str]:
        """Convert fills/strokes to Tailwind colors"""
        classes = []
        
        # Background
        if node.fills and len(node.fills) > 0:
            fill = node.fills[0]
            if fill.get("type") == "SOLID":
                color = fill.get("color", {})
                bg_class = TailwindConverter._color_to_tailwind(color, "bg")
                if bg_class:
                    classes.append(bg_class)
        
        # Border
        if node.strokes and len(node.strokes) > 0:
            stroke = node.strokes[0]
            if stroke.get("type") == "SOLID":
                color = stroke.get("color", {})
                weight = node.raw.get("strokeWeight", 1)
                classes.append(f"border-[{weight}px]")
                border_class = TailwindConverter._color_to_tailwind(color, "border")
                if border_class:
                    classes.append(border_class)
        
        # Border radius - use exact pixel values
        if node.corner_radius > 0:
            cr = int(round(node.corner_radius))
            radius_map = {2: "rounded-sm", 4: "rounded", 6: "rounded-md", 8: "rounded-lg",
                         12: "rounded-xl", 16: "rounded-2xl", 24: "rounded-3xl"}
            if cr >= 9999:
                classes.append("rounded-full")
            elif cr in radius_map:
                classes.append(radius_map[cr])
            else:
                classes.append(f"rounded-[{cr}px]")
        
        return classes
    
    @staticmethod
    def get_text_classes(node: FigmaNode) -> List[str]:
        """Convert text styles to Tailwind"""
        if node.type != "TEXT":
            return []
        
        classes = []
        style = node.style

        # Font size - use exact values
        size = style.get("fontSize", 16)
        font_size_map = {
            10: "text-[10px]", 11: "text-[11px]", 12: "text-xs", 13: "text-[13px]",
            14: "text-sm", 15: "text-[15px]", 16: "text-base", 18: "text-lg",
            20: "text-xl", 24: "text-2xl", 30: "text-3xl", 36: "text-4xl",
            48: "text-5xl", 60: "text-6xl", 72: "text-7xl"
        }
        if size in font_size_map:
            classes.append(font_size_map[size])
        else:
            classes.append(f"text-[{int(size)}px]")
        
        # Font weight
        weight = style.get("fontWeight", 400)
        if weight <= 300:
            classes.append("font-light")
        elif weight == 400:
            classes.append("font-normal")
        elif weight == 500:
            classes.append("font-medium")
        elif weight == 600:
            classes.append("font-semibold")
        elif weight >= 700:
            classes.append("font-bold")
        
        # Text align
        align = style.get("textAlignHorizontal", "LEFT")
        if align == "CENTER":
            classes.append("text-center")
        elif align == "RIGHT":
            classes.append("text-right")
        elif align == "JUSTIFIED":
            classes.append("text-justify")
        
        # Line height
        line_height = style.get("lineHeightPx")
        if line_height and size:
            ratio = line_height / size
            if abs(ratio - 1.0) < 0.1:
                classes.append("leading-none")
            elif abs(ratio - 1.25) < 0.1:
                classes.append("leading-tight")
            elif abs(ratio - 1.5) < 0.1:
                classes.append("leading-normal")
            elif abs(ratio - 1.75) < 0.1:
                classes.append("leading-relaxed")
            elif abs(ratio - 2.0) < 0.1:
                classes.append("leading-loose")

        # Letter spacing
        letter_spacing = style.get("letterSpacing")
        if letter_spacing and letter_spacing != 0:
            ls = round(letter_spacing, 2)
            if ls > 0:
                classes.append(f"tracking-[{ls}px]")

        # Text color
        if node.fills and len(node.fills) > 0:
            fill = node.fills[0]
            if fill.get("type") == "SOLID":
                color = fill.get("color", {})
                text_class = TailwindConverter._color_to_tailwind(color, "text")
                if text_class:
                    classes.append(text_class)

        return classes
    
    @staticmethod
    def get_effect_classes(node: FigmaNode) -> List[str]:
        """Convert effects to Tailwind"""
        classes = []
        
        for effect in node.effects:
            if effect.get("type") == "DROP_SHADOW":
                radius = effect.get("radius", 0)
                if radius <= 2:
                    classes.append("shadow-sm")
                elif radius <= 4:
                    classes.append("shadow")
                elif radius <= 8:
                    classes.append("shadow-md")
                elif radius <= 16:
                    classes.append("shadow-lg")
                else:
                    classes.append("shadow-xl")
        
        # Opacity
        if node.opacity < 1:
            opacity_percent = int(node.opacity * 100)
            classes.append(f"opacity-{opacity_percent}")
        
        return classes
    
    @staticmethod
    def _size_to_tailwind(size: float, prefix: str) -> str:
        """Convert pixel size to exact Tailwind spacing using arbitrary values"""
        size = int(round(size))
        if size == 0:
            return f"{prefix}-0"

        # Use standard Tailwind values for common sizes (multiples of 4px)
        standard_px = {
            1: "px", 2: "0.5", 4: "1", 6: "1.5", 8: "2", 10: "2.5",
            12: "3", 14: "3.5", 16: "4", 20: "5", 24: "6", 28: "7",
            32: "8", 36: "9", 40: "10", 44: "11", 48: "12",
            56: "14", 64: "16", 80: "20", 96: "24"
        }

        if size in standard_px:
            return f"{prefix}-{standard_px[size]}"

        # For non-standard sizes, use exact pixel value
        return f"{prefix}-[{size}px]"

    @staticmethod
    def _color_to_tailwind(color: Dict, prefix: str) -> Optional[str]:
        """Convert RGB color to exact hex Tailwind class"""
        r = int(color.get("r", 0) * 255)
        g = int(color.get("g", 0) * 255)
        b = int(color.get("b", 0) * 255)

        # Pure white/black - use standard names
        if r >= 255 and g >= 255 and b >= 255:
            return f"{prefix}-white"
        if r == 0 and g == 0 and b == 0:
            return f"{prefix}-black"

        # Transparent check
        a = color.get("a", 1)
        if a == 0:
            return f"{prefix}-transparent"

        # Use exact hex color for everything else
        hex_color = f"#{r:02x}{g:02x}{b:02x}"
        return f"{prefix}-[{hex_color}]"


class ResponsiveLayoutEngine:
    """Handles responsive layout conversion"""
    
    @staticmethod
    def get_responsive_classes(node: FigmaNode) -> List[str]:
        """Add responsive breakpoints"""
        classes = []
        
        constraints = node.constraints
        h_constraint = constraints.get("horizontal", "LEFT")
        v_constraint = constraints.get("vertical", "TOP")
        
        # Horizontal constraints
        if h_constraint == "LEFT_RIGHT":
            classes.append("w-full")
        elif h_constraint == "CENTER":
            classes.append("mx-auto")
        elif h_constraint == "RIGHT":
            classes.append("ml-auto")
        elif h_constraint == "SCALE":
            classes.append("w-full")
        
        # Vertical constraints
        if v_constraint == "TOP_BOTTOM":
            classes.append("h-full")
        elif v_constraint == "CENTER":
            classes.append("my-auto")
        elif v_constraint == "BOTTOM":
            classes.append("mt-auto")
        
        return classes


class ImageDownloader:
    """Downloads and manages images from Figma"""
    
    def __init__(self, figma_token: str):
        self.figma_token = figma_token
        self.api_base = "https://api.figma.com/v1"
        
    async def download_images(self, file_id: str, nodes: List[FigmaNode], output_dir: Path) -> Dict[str, str]:
        """Download all images and return mapping of node_id -> local_path"""
        # Collect all nodes with fills (images)
        image_nodes = []
        for node in nodes:
            if self._has_image_fill(node):
                image_nodes.append(node)
        
        if not image_nodes:
            return {}
        
        # Get image URLs from Figma
        node_ids = [n.id for n in image_nodes]
        image_urls = await self._fetch_image_urls(file_id, node_ids)
        
        # Download images
        images_dir = output_dir / "public" / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        
        image_map = {}
        async with aiohttp.ClientSession() as session:
            for node in image_nodes:
                if node.id in image_urls:
                    url = image_urls[node.id]
                    if not url:
                        logger.warning(f"Figma returned null URL for node {node.id}, skipping")
                        continue
                    # Sanitize filename - replace : with _ for Windows compatibility
                    safe_id = node.id.replace(':', '_').replace('/', '_')
                    filename = f"{safe_id}.png"
                    filepath = images_dir / filename

                    await self._download_file(session, url, filepath)

                    # Only add to map if file actually downloaded
                    if filepath.exists() and filepath.stat().st_size > 0:
                        image_map[node.id] = f"/images/{filename}"
                        logger.info(f"Downloaded image: {filename}")
                    else:
                        logger.warning(f"Image download empty/failed for {node.id}")
                else:
                    logger.debug(f"No URL returned by Figma for node {node.id}")

        logger.info(f"Image download complete: {len(image_map)}/{len(image_nodes)} images downloaded")
        return image_map
    
    def _has_image_fill(self, node: FigmaNode) -> bool:
        """Check if node has image fill"""
        for fill in node.fills:
            if fill.get("type") == "IMAGE":
                return True
        return False
    
    async def _fetch_image_urls(self, file_id: str, node_ids: List[str]) -> Dict[str, str]:
        """Fetch image URLs from Figma API — with retry on 429 rate limit"""
        if not node_ids:
            return {}

        headers = {"X-Figma-Token": self.figma_token}
        # Process at most 100 node IDs at a time (Figma API limit)
        ids_param = ",".join(node_ids[:100])
        url = f"{self.api_base}/images/{file_id}"
        params = {"ids": ids_param, "format": "png", "scale": 2}

        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=30)) as response:
                        if response.status == 200:
                            data = await response.json()
                            return data.get("images", {})
                        if response.status == 429:
                            wait = min(60, 15 * (2 ** attempt))
                            logger.warning(f"Image API rate limit (429). Waiting {wait}s (attempt {attempt + 1}/{max_retries})")
                            await asyncio.sleep(wait)
                            continue
                        logger.warning(f"Image fetch returned {response.status}")
                        return {}
            except Exception as e:
                logger.warning(f"Image fetch attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(5)
        return {}
    
    async def _download_file(self, session: aiohttp.ClientSession, url: str, filepath: Path):
        """Download file from URL"""
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    content = await response.read()
                    with open(filepath, "wb") as f:
                        f.write(content)
                else:
                    logger.warning(f"Image download returned {response.status}: {url[:80]}")
        except Exception as e:
            logger.warning(f"Image download failed: {e}")


class ReactCodeGenerator:
    """Generates production-ready React + Tailwind code"""
    
    def __init__(self):
        self.tailwind = TailwindConverter()
        self.responsive = ResponsiveLayoutEngine()
        
    def generate_component(self, node: FigmaNode, component_name: str, image_map: Dict[str, str]) -> str:
        """Generate React component from Figma node"""
        jsx = self._generate_jsx(node, image_map, indent=2, parent=None)
        
        # Generate imports
        imports = ["import React from 'react'"]
        
        # Check if images are used
        if any(node.id in image_map for node in self._get_all_nodes(node)):
            imports.append("import Image from 'next/image'")
        
        imports_str = "\n".join(imports)
        
        return f'''{imports_str}

export default function {component_name}() {{
  return (
{jsx}
  )
}}
'''
    
    def _generate_jsx(self, node: FigmaNode, image_map: Dict[str, str], indent: int = 0, parent: Optional[FigmaNode] = None) -> str:
        """Recursively generate JSX.

        Key behaviours:
        - Always recurses into ALL children (no longer gated on auto-layout).
        - Adds `absolute left-[x]px top-[y]px` to children whose parent has no
          auto-layout, using relative coordinates inside that parent.
        - Adds `relative` to container nodes that have absolute-positioned children.
        """
        if not node.visible:
            return ""

        ind = "  " * indent
        lines = []

        # Determine element type
        element = self._get_element_type(node, image_map)

        # Collect all Tailwind classes
        classes = []
        classes.extend(self.tailwind.get_layout_classes(node))
        classes.extend(self.tailwind.get_spacing_classes(node))
        classes.extend(self.tailwind.get_sizing_classes(node))
        classes.extend(self.tailwind.get_color_classes(node))
        classes.extend(self.tailwind.get_text_classes(node))
        classes.extend(self.tailwind.get_effect_classes(node))
        classes.extend(self.responsive.get_responsive_classes(node))

        # --- BUG 4 FIX: absolute positioning when parent has no auto-layout ---
        if parent is not None and not parent.has_auto_layout and node.absolute_bounds:
            parent_x = parent.absolute_bounds.get("x", 0)
            parent_y = parent.absolute_bounds.get("y", 0)
            node_x = node.absolute_bounds.get("x", 0)
            node_y = node.absolute_bounds.get("y", 0)
            rel_x = int(node_x - parent_x)
            rel_y = int(node_y - parent_y)
            classes.append("absolute")
            classes.append(f"left-[{rel_x}px]" if rel_x != 0 else "left-0")
            classes.append(f"top-[{rel_y}px]" if rel_y != 0 else "top-0")

        # Container nodes with no auto-layout need `relative` so their absolute
        # children are positioned correctly inside them.
        if (node.children and not node.has_auto_layout
                and node.type in ["FRAME", "GROUP", "COMPONENT", "INSTANCE"]):
            classes.append("relative")

        # Build className string
        class_str = " ".join(classes)

        # Opening tag
        if element == "img":
            # Next.js Image component — skip if no valid src (empty src crashes build)
            img_src = image_map.get(node.id, "")
            if not img_src:
                # Render as a placeholder div with same dimensions
                lines.append(f'{ind}<div{f" className=\"{class_str}\"" if class_str else ""} />')
                return "\n".join(lines)
            lines.append(f'{ind}<Image')
            lines.append(f'{ind}  src="{img_src}"')
            lines.append(f'{ind}  alt="{node.name}"')
            lines.append(f'{ind}  width={{{int(node.width)}}}')
            lines.append(f'{ind}  height={{{int(node.height)}}}')
            if class_str:
                lines.append(f'{ind}  className="{class_str}"')
            lines.append(f'{ind}/>')
            return "\n".join(lines)

        # Regular element
        lines.append(f'{ind}<{element}{f" className=\"{class_str}\"" if class_str else ""}>')

        # Text content — BUG 5 FIX: multi-line handled inline with <br />
        # Also escape JSX-unsafe chars: { } < & so TypeScript doesn't choke
        if node.type == "TEXT" and node.characters:
            def _escape_jsx(s: str) -> str:
                return (s
                    .replace('&', '&amp;')
                    .replace('{', '&#123;')
                    .replace('}', '&#125;')
                    .replace('<', '&lt;')
                    .replace('>', '&gt;'))

            text_content = node.characters
            if '\n' in text_content:
                parts = text_content.split('\n')
                for i, part in enumerate(parts):
                    if part:
                        lines.append(f'{ind}  {_escape_jsx(part)}')
                    if i < len(parts) - 1:
                        lines.append(f'{ind}  <br />')
            else:
                lines.append(f'{ind}  {_escape_jsx(text_content)}')

        # --- BUG 2 FIX: always recurse into ALL children, pass self as parent ---
        for child in node.children:
            child_jsx = self._generate_jsx(child, image_map, indent + 1, parent=node)
            if child_jsx:
                lines.append(child_jsx)

        # Closing tag
        lines.append(f'{ind}</{element}>')

        return "\n".join(lines)
    
    def _get_element_type(self, node: FigmaNode, image_map: Dict[str, str]) -> str:
        """Determine HTML element type"""
        if node.id in image_map:
            return "img"
        if node.type == "TEXT":
            # Determine semantic element based on size
            size = node.style.get("fontSize", 16)
            if size >= 32:
                return "h1"
            elif size >= 24:
                return "h2"
            elif size >= 20:
                return "h3"
            else:
                return "p"
        return "div"
    
    def _get_all_nodes(self, node: FigmaNode) -> List[FigmaNode]:
        """Get all nodes recursively"""
        nodes = [node]
        for child in node.children:
            nodes.extend(self._get_all_nodes(child))
        return nodes


class AICodeGenerator:
    """AI-powered code generation using Groq vision model for pixel-perfect output"""

    def __init__(self):
        self.groq_client = None
        self.model = "meta-llama/llama-4-scout-17b-16e-instruct"
        try:
            from groq import Groq
            api_key = os.getenv("GROQ_API_KEY")
            if api_key:
                self.groq_client = Groq(api_key=api_key)
                logger.info("AI Code Generator: Groq vision enabled")
        except ImportError:
            logger.warning("AI Code Generator: groq package not installed")

    @property
    def available(self):
        return self.groq_client is not None

    def generate_component(
        self,
        node: FigmaNode,
        component_name: str,
        image_map: Dict[str, str],
        figma_screenshot_path: str = None
    ) -> Optional[str]:
        """Generate component code using AI vision model"""
        if not self.groq_client:
            return None

        try:
            # Build simplified structure for the prompt
            structure = self._simplify_node(node, image_map, depth=0)
            image_refs = [f"  /images/{path.split('/')[-1]}" for _, path in image_map.items()]

            prompt = self._build_prompt(component_name, structure, image_refs)

            # System message enforces structure at the model level — the user prompt
            # then provides the mandatory skeleton with exact Figma dimensions.
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a pixel-perfect Figma-to-React code generator. "
                        "You output ONLY raw TSX — no markdown, no explanation. "
                        "When the prompt supplies a MANDATORY LAYOUT SKELETON you MUST output "
                        "that exact outer structure verbatim, filling only the inner {{/* FILL */}} slots. "
                        "NEVER move, rename, or reorder the outer <div>, <aside>, or right-panel <div>. "
                        "The sidebar is ALWAYS the first child of the root flex div. "
                        "NEVER put a full-width <header> before the sidebar."
                    ),
                }
            ]

            # If screenshot available, use vision
            if figma_screenshot_path and Path(figma_screenshot_path).exists():
                import base64
                with open(figma_screenshot_path, "rb") as f:
                    img_b64 = base64.b64encode(f.read()).decode()

                messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{img_b64}"}
                        },
                        {"type": "text", "text": prompt}
                    ]
                })
            else:
                messages.append({"role": "user", "content": prompt})

            logger.info(f"AI generating component: {component_name}")
            response = self.groq_client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.1,
                max_tokens=16000
            )

            code = response.choices[0].message.content

            # Extract code from markdown code blocks
            if "```" in code:
                match = re.search(r'```(?:tsx|jsx|typescript|javascript)?\n(.*?)```', code, re.DOTALL)
                if match:
                    code = match.group(1).strip()

            # Validate it has export default
            if "export default" not in code:
                code = f'{code}\n\nexport default function {component_name}() {{ return <div>Error</div> }}'

            logger.info(f"AI generated {len(code)} chars for {component_name}")
            return code

        except Exception as e:
            logger.error(f"AI code generation failed: {e}")
            return None

    def _simplify_node(self, node: FigmaNode, image_map: Dict, depth: int = 0) -> Dict:
        """Create simplified node structure with full CSS properties for AI prompt"""
        result = {
            "name": node.name,
            "type": node.type,
            "w": int(node.width),
            "h": int(node.height),
        }

        # Auto-layout / Flexbox properties
        if node.has_auto_layout:
            result["layout"] = node.layout_mode.lower()  # "horizontal" or "vertical"
            if node.item_spacing > 0:
                result["gap"] = int(node.item_spacing)
            # Alignment (maps to justify-content / align-items)
            result["justify"] = node.primary_axis_align.lower()    # min/center/max/space_between
            result["align"] = node.counter_axis_align.lower()      # min/center/max/baseline
            # Sizing mode
            if node.primary_axis_sizing == "FILL":
                result["widthMode"] = "fill"
            if node.counter_axis_sizing == "FILL":
                result["heightMode"] = "fill"

        # Padding
        p = node.padding
        has_padding = any(v > 0 for v in p.values())
        if has_padding:
            if p["top"] == p["right"] == p["bottom"] == p["left"]:
                result["padding"] = int(p["top"])
            else:
                result["padding"] = f"{int(p['top'])} {int(p['right'])} {int(p['bottom'])} {int(p['left'])}"

        # Background color
        if node.fills:
            for fill in node.fills:
                if fill.get("type") == "SOLID" and fill.get("visible", True):
                    c = fill["color"]
                    r, g, b = int(c["r"]*255), int(c["g"]*255), int(c["b"]*255)
                    a = fill.get("opacity", c.get("a", 1))
                    if a < 1:
                        result["bg"] = f"rgba({r},{g},{b},{round(a,2)})"
                    else:
                        result["bg"] = f"#{r:02x}{g:02x}{b:02x}"
                elif fill.get("type") == "GRADIENT_LINEAR":
                    result["bg"] = "linear-gradient"

        # Border / Stroke
        if node.strokes:
            for stroke in node.strokes:
                if stroke.get("type") == "SOLID" and stroke.get("visible", True):
                    c = stroke["color"]
                    r, g, b = int(c["r"]*255), int(c["g"]*255), int(c["b"]*255)
                    weight = node.raw.get("strokeWeight", 1)
                    result["border"] = f"{weight}px #{r:02x}{g:02x}{b:02x}"

        # Corner radius
        if node.corner_radius > 0:
            result["radius"] = int(node.corner_radius)

        # Opacity
        if node.opacity < 1:
            result["opacity"] = round(node.opacity, 2)

        # Effects (shadows)
        for effect in node.effects:
            if effect.get("type") == "DROP_SHADOW" and effect.get("visible", True):
                offset = effect.get("offset", {})
                result["shadow"] = {
                    "x": offset.get("x", 0),
                    "y": offset.get("y", 0),
                    "blur": effect.get("radius", 0),
                    "spread": effect.get("spread", 0)
                }
                break

        # Text properties (full CSS)
        if node.type == "TEXT" and node.characters:
            result["text"] = node.characters[:150]
            style = node.style
            result["css"] = {}
            if style.get("fontSize"):
                result["css"]["fontSize"] = f"{int(style['fontSize'])}px"
            if style.get("fontWeight"):
                result["css"]["fontWeight"] = style["fontWeight"]
            if style.get("fontFamily"):
                result["css"]["fontFamily"] = style["fontFamily"]
            if style.get("lineHeightPx"):
                result["css"]["lineHeight"] = f"{round(style['lineHeightPx'], 1)}px"
            if style.get("letterSpacing"):
                result["css"]["letterSpacing"] = f"{round(style['letterSpacing'], 1)}px"
            if style.get("textAlignHorizontal"):
                result["css"]["textAlign"] = style["textAlignHorizontal"].lower()
            # Text color
            if node.fills:
                for fill in node.fills:
                    if fill.get("type") == "SOLID":
                        c = fill["color"]
                        r, g, b = int(c["r"]*255), int(c["g"]*255), int(c["b"]*255)
                        result["css"]["color"] = f"#{r:02x}{g:02x}{b:02x}"

        # Image reference
        if node.id in image_map:
            result["image"] = image_map[node.id]

        # Children (limit depth to 8 levels to capture nested sidebars, cards, grids)
        if depth < 8 and node.children:
            visible_children = [c for c in node.children if c.visible]

            # Deduplicate repeating groups ONLY at depth >= 4 (where cards live).
            # Depth 0-3 covers the frame root, sidebar, nav containers and nav items —
            # these MUST all be serialized in full so the AI generates the complete sidebar.
            # Cards are typically at depth 4+ (frame > main > content > grid > cards).
            items_have_images = any(c.id in image_map for c in visible_children)
            if (depth >= 4
                    and len(visible_children) >= 5
                    and all(c.type == visible_children[0].type for c in visible_children)
                    and items_have_images):
                result["children"] = [
                    self._simplify_node(c, image_map, depth + 1)
                    for c in visible_children[:2]
                ]
                result["children_total"] = len(visible_children)
                result["children_note"] = (
                    f"Repeating group: {len(visible_children)} image cards total, "
                    f"first 2 shown as examples. Render ALL {len(visible_children)} in code "
                    f"using the same pattern with different images from the available list."
                )
            else:
                result["children"] = [
                    self._simplify_node(child, image_map, depth + 1)
                    for child in visible_children
                ]

        return result

    def _analyze_layout(self, structure: Dict):
        """Detect top-level layout pattern.

        Returns: (hint_str, layout_info) where layout_info is a dict or None.
        layout_info keys: type, root_bg, sidebar, topbar, content_bg, total_w, total_h
        """
        children = structure.get("children", [])
        if len(children) < 2:
            return "", None

        total_w = structure.get("w", 1440) or 1440
        total_h = structure.get("h", 900) or 900
        hints = []
        sidebar = None
        topbar = None
        content = None

        for i, child in enumerate(children[:5]):
            w = child.get("w", 0)
            h = child.get("h", 0)
            name = child.get("name", f"child_{i}")
            bg = child.get("bg", "")

            # Sidebar: narrow (< 28% width) AND tall (> 70% height)
            if w > 0 and h > 0 and w < total_w * 0.28 and h > total_h * 0.70:
                if sidebar is None:  # take the first match
                    sidebar = {"name": name, "w": w, "h": h, "bg": bg}
                    hints.append(
                        f"SIDEBAR DETECTED: \"{name}\" (w={w}px, h={h}px, bg={bg})"
                    )
            # Topbar: wide (> 55% width) AND short (< 18% height)
            elif w > total_w * 0.55 and 0 < h < total_h * 0.18:
                if topbar is None:
                    topbar = {"name": name, "w": w, "h": h, "bg": bg}
                    hints.append(
                        f"TOPBAR DETECTED: \"{name}\" (w={w}px, h={h}px, bg={bg})"
                    )
            # Content panel: wide (> 50% width) AND tall (> 50% height)
            elif w > total_w * 0.50 and h > total_h * 0.50:
                if content is None:
                    content = {"name": name, "w": w, "h": h, "bg": bg}

        if not sidebar:
            return ("\n".join(hints) + "\n") if hints else "", None

        layout_info = {
            "type": "sidebar+content",
            "root_bg": structure.get("bg", ""),
            "sidebar": sidebar,
            "topbar": topbar,
            "content_bg": content.get("bg", "") if content else "",
            "total_w": total_w,
            "total_h": total_h,
        }
        hint_str = ("LAYOUT HINTS:\n" + "\n".join(hints) + "\n") if hints else ""
        return hint_str, layout_info

    def _build_layout_skeleton(self, layout_info: Dict, component_name: str) -> str:
        """Build the MANDATORY JSX layout skeleton from detected Figma structure.

        The skeleton uses the exact pixel dimensions and colours from Figma so the
        AI cannot accidentally produce the wrong outer structure.  It only needs to
        fill in the inner content slots marked with {{/* FILL: ... */}}.
        """
        sidebar = layout_info["sidebar"]
        topbar = layout_info.get("topbar")
        root_bg = layout_info.get("root_bg", "")
        content_bg = layout_info.get("content_bg", "")

        sidebar_w = sidebar["w"]
        sidebar_bg = sidebar.get("bg", "")

        def bg_cls(hex_val):
            return f" bg-[{hex_val}]" if hex_val and hex_val.startswith("#") else ""

        root_bg_cls = bg_cls(root_bg) or bg_cls(sidebar_bg)
        sidebar_bg_cls = bg_cls(sidebar_bg)
        content_bg_cls = bg_cls(content_bg)

        if topbar:
            topbar_h = topbar.get("h", 64)
            topbar_bg = topbar.get("bg", "")
            topbar_bg_cls = bg_cls(topbar_bg) if topbar_bg else " bg-white"
            right_panel = (
                f'  <div className="flex-1 flex flex-col min-w-0 overflow-hidden{content_bg_cls}">\n'
                f'    <header className="flex-shrink-0 h-[{topbar_h}px]{topbar_bg_cls} flex items-center px-6 border-b border-black/10">\n'
                f'      {{/* FILL: topbar — page title, search bar, action buttons. Render ALL elements visible in the screenshot. */}}\n'
                f'    </header>\n'
                f'    <main className="flex-1 overflow-y-auto">\n'
                f'      {{/* FILL: filter tabs, card grid, tables — ALL content visible in the screenshot. */}}\n'
                f'    </main>\n'
                f'  </div>'
            )
        else:
            right_panel = (
                f'  <div className="flex-1 flex flex-col min-w-0 overflow-hidden{content_bg_cls}">\n'
                f'    <main className="flex-1 overflow-y-auto">\n'
                f'      {{/* FILL: ALL content visible in the screenshot — headers, filters, grids, tables. */}}\n'
                f'    </main>\n'
                f'  </div>'
            )

        return (
            f'━━━ MANDATORY LAYOUT SKELETON — DO NOT CHANGE THE OUTER STRUCTURE ━━━\n'
            f'Your output MUST start with exactly this wrapper (fill in the {{/* FILL */}} slots):\n\n'
            f'import Image from \'next/image\'\n\n'
            f'export default function {component_name}() {{\n'
            f'  return (\n'
            f'    <div className="flex h-screen overflow-hidden{root_bg_cls}">\n'
            f'      <aside className="w-[{sidebar_w}px] flex-shrink-0 h-full flex flex-col{sidebar_bg_cls} overflow-y-auto">\n'
            f'        {{/* FILL: logo + ALL nav items exactly as in the screenshot. */}}\n'
            f'      </aside>\n'
            f'{right_panel}\n'
            f'    </div>\n'
            f'  )\n'
            f'}}\n\n'
            f'Replace each {{/* FILL: ... */}} with real JSX. DO NOT change any className on the outer divs/aside.'
        )

    def _build_prompt(self, component_name: str, structure: Dict, image_refs: List[str]) -> str:
        """Build the prompt for AI code generation"""
        images_list = "\n".join(image_refs) if image_refs else "  (none)"

        # Truncate structure to avoid token limits
        structure_str = json.dumps(structure, indent=1)
        if len(structure_str) > 18000:
            structure_str = structure_str[:18000] + "\n... (truncated - rely on the screenshot for remaining details)"

        # Detect layout and build mandatory skeleton if sidebar found
        layout_hint, layout_info = self._analyze_layout(structure)

        if layout_info and layout_info.get("type") == "sidebar+content":
            skeleton_section = self._build_layout_skeleton(layout_info, component_name) + "\n\n"
        else:
            skeleton_section = ""

        return f"""You are a pixel-perfect Figma-to-React converter. Reproduce EVERY element in the screenshot as a single React + Tailwind CSS component.

Component name: {component_name}

Available images (use these exact paths — never invent paths):
{images_list}

{layout_hint}{skeleton_section}Figma structure data (exact colors, sizes, spacing — use these values):
{structure_str}

━━━ RENDER EVERY SECTION IN FULL ━━━

SIDEBAR RULES:
- Generate ALL navigation items visible in the screenshot (every icon + label pair, every section divider).
- Use exact background color and item spacing from structure data.
- Active/selected nav item: highlighted background or border-left accent.

HEADER / TOPBAR RULES (goes INSIDE the right panel, not above the sidebar):
- Page title (with back arrow if present), search bar, date range picker, action buttons.
- Exact colors and border from structure data.

CARD GRID RULES:
- Count columns from the screenshot and use `grid grid-cols-N gap-[Xpx]`.
- Generate ALL visible cards as an inline data array mapped to JSX.
- Each card: background image with `<Image src="..." fill className="object-cover" alt="...">` inside `<div className="relative w-full h-[Xpx] overflow-hidden">`, overlay gradient, badge(s), title, meta text, status chip, action buttons.

FILTER TABS RULES:
- ALL tabs with label + count badge; active tab uses exact highlight color from structure.

━━━ HARD RULES ━━━
1. Output raw TSX only — no markdown fences, no explanation.
2. Every {{/* FILL */}} slot gets real JSX — no empty comments left behind.
3. EXACT colors: bg-[#rrggbb] from structure. NEVER substitute named Tailwind colors.
4. EXACT sizes: w-[Xpx], gap-[Xpx], text-[Xpx] from structure data.
5. Images: import Image from 'next/image'. Use only paths from the Available Images list. Never empty src.
6. Static only — no useState, no useEffect.
7. JSX text nodes: escape {{ as &#123; and }} as &#125;."""


class ProductionFigmaToCode:
    """Production-grade Figma to code converter"""

    def __init__(self, figma_token: str):
        self.figma_token = figma_token
        self.api_base = "https://api.figma.com/v1"
        self.component_extractor = ComponentExtractor()
        self.code_generator = ReactCodeGenerator()
        self.ai_generator = AICodeGenerator()
        self.image_downloader = ImageDownloader(figma_token)
    
    async def _export_frame_image(self, file_id: str, node_id: str, output_dir: Path) -> Optional[str]:
        """Export a specific Figma frame as PNG using the images API.

        Caches the result so repeated runs don't re-hit the API.
        Returns the local file path, or None if export fails.
        """
        safe_id = node_id.replace(":", "_").replace(";", "_")
        cache_path = output_dir / f"_frame_{safe_id}.png"

        # Return cached file if valid
        if cache_path.exists() and cache_path.stat().st_size > 10_000:
            logger.info(f"Using cached frame screenshot: {cache_path.name}")
            return str(cache_path)

        try:
            headers = {"X-Figma-Token": self.figma_token}
            resp = requests.get(
                f"{self.api_base}/images/{file_id}",
                headers=headers,
                params={"ids": node_id, "format": "png", "scale": "1"},
                timeout=30,
            )
            if resp.status_code != 200:
                logger.warning(f"Figma images API returned {resp.status_code} for frame {node_id}")
                return None

            image_url = resp.json().get("images", {}).get(node_id)
            if not image_url:
                logger.warning(f"No image URL returned for frame {node_id}")
                return None

            # Download the rendered frame PNG from S3
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    image_url, timeout=aiohttp.ClientTimeout(total=60)
                ) as r:
                    if r.status == 200:
                        data = await r.read()
                        if len(data) > 1000:
                            cache_path.write_bytes(data)
                            logger.info(
                                f"Frame screenshot exported: {cache_path.name} "
                                f"({len(data) // 1024}KB)"
                            )
                            return str(cache_path)
                    logger.warning(f"Frame image download failed: HTTP {r.status}")
        except Exception as e:
            logger.warning(f"Could not export frame image for {node_id}: {e}")

        return None

    async def convert(self, figma_url: str, output_dir: Path, figma_screenshot_path: str = None) -> Dict:
        """Convert Figma to production-ready code"""
        try:
            file_id = self._extract_file_id(figma_url)
            logger.info(f"🎨 Converting Figma file: {file_id}")
            
            # Fetch Figma file — run in executor so time.sleep inside _fetch_file
            # doesn't block the asyncio event loop during rate-limit waits.
            loop = asyncio.get_event_loop()
            figma_data = await loop.run_in_executor(None, self._fetch_file, file_id)
            logger.info("✅ Fetched Figma data")
            
            # Parse structure
            document = figma_data.get("document", {})
            root = FigmaNode(document)
            
            # Extract components
            self.component_extractor.extract(root)
            logger.info(f"✅ Found {len(self.component_extractor.components)} components")
            
            # Get all frames (screens)
            frames = self._get_frames(root)
            logger.info(f"✅ Found {len(frames)} screens")
            
            if not frames:
                raise Exception("No frames found in Figma file")
            
            # Create output structure (Next.js App Router with src/)
            output_dir.mkdir(parents=True, exist_ok=True)
            components_dir = output_dir / "src" / "components"
            components_dir.mkdir(parents=True, exist_ok=True)
            
            # Ensure public/images directory always exists so git commits it
            (output_dir / "public" / "images").mkdir(parents=True, exist_ok=True)

            # Download images
            all_nodes = []
            for frame in frames:
                all_nodes.extend(self.code_generator._get_all_nodes(frame))
            image_map = await self.image_downloader.download_images(file_id, all_nodes, output_dir)
            logger.info(f"✅ Downloaded {len(image_map)} images")

            # ——— Pre-fetch file thumbnail as fallback visual reference ———
            _file_thumbnail_path = figma_screenshot_path  # use caller-provided if available
            if not _file_thumbnail_path:
                thumbnail_url = figma_data.get("thumbnailUrl")
                if thumbnail_url:
                    try:
                        thumb_path = output_dir / "_figma_thumb.png"
                        async with aiohttp.ClientSession() as _thumb_session:
                            async with _thumb_session.get(
                                thumbnail_url, timeout=aiohttp.ClientTimeout(total=30)
                            ) as _resp:
                                if _resp.status == 200:
                                    thumb_path.write_bytes(await _resp.read())
                                    _file_thumbnail_path = str(thumb_path)
                                    logger.info(f"File thumbnail ready: {thumb_path.name} ({thumb_path.stat().st_size // 1024}KB)")
                    except Exception as _e:
                        logger.warning(f"Could not fetch file thumbnail: {_e}")

            # Generate components
            # AI is enabled by default — produces pixel-perfect output using Groq vision model.
            # Set USE_AI=false to force programmatic-only mode (faster, lower quality).
            use_ai = os.getenv('USE_AI', 'true').lower() == 'true'
            logger.info(f"🔧 Code generation mode: {'AI (pixel-perfect)' if use_ai else 'PROGRAMMATIC'}")

            generated = []
            for frame in frames:
                comp_name = self._sanitize_name(frame.name)
                logger.info(f"🔨 Generating: {comp_name}")

                # ——— Per-frame screenshot: gives AI the exact frame to replicate ———
                # Try the Figma images API first (highest quality, frame-specific).
                # Fall back to file thumbnail if export fails (e.g. rate limit).
                _ai_screenshot_path = await self._export_frame_image(file_id, frame.id, output_dir)
                if _ai_screenshot_path:
                    logger.info(f"Using per-frame screenshot for AI: {Path(_ai_screenshot_path).name}")
                elif _file_thumbnail_path:
                    _ai_screenshot_path = _file_thumbnail_path
                    logger.info(f"Using file thumbnail as fallback for AI")
                else:
                    logger.warning(f"No screenshot available for AI — quality may be reduced")

                code = None

                if use_ai:
                    if self.ai_generator.available:
                        logger.info(f"🤖 [AI PATH] Generating {comp_name} with Groq vision model")
                        code = self.ai_generator.generate_component(
                            frame, comp_name, image_map, _ai_screenshot_path
                        )
                        if code:
                            logger.info(f"✅ [AI PATH] {comp_name} generated successfully")
                        else:
                            logger.warning(f"⚠️ [AI PATH] Failed for {comp_name}, falling back to programmatic")
                    else:
                        logger.warning(f"⚠️ USE_AI=true but GROQ_API_KEY not set — using programmatic path")

                # Programmatic generation (default path or AI fallback)
                if not code:
                    logger.info(f"⚙️ [PROGRAMMATIC PATH] Generating {comp_name}")
                    code = self.code_generator.generate_component(frame, comp_name, image_map)
                    logger.info(f"✅ [PROGRAMMATIC PATH] {comp_name} generated successfully")

                comp_file = components_dir / f"{comp_name}.tsx"
                with open(comp_file, "w", encoding="utf-8") as f:
                    f.write(code)

                generated.append({
                    "name": comp_name,
                    "file": str(comp_file),
                    "original": frame.name,
                    "node_id": frame.id,
                    "node_type": frame.type,
                })
            
            # Generate supporting files (complete Next.js App Router structure)
            self._generate_nextjs_structure(output_dir, generated)
            self._generate_package_json(output_dir)
            self._generate_tailwind_config(output_dir)
            self._generate_postcss_config(output_dir)
            self._generate_next_config(output_dir)
            self._generate_tsconfig(output_dir)
            self._generate_gitignore(output_dir)
            self._generate_readme(output_dir, figma_url)

            # Write component registry — must come AFTER all TSX files are on disk
            registry_path = self._write_component_registry(
                output_dir, file_id, figma_data.get("name", "Untitled"), generated
            )

            logger.info("🎉 Conversion complete!")

            return {
                "success": True,
                "components": generated,
                "images": len(image_map),
                "output_dir": str(output_dir),
                "file_name": figma_data.get("name", "Untitled"),
                "first_frame_node_id": frames[0].id if frames else None,
                "thumbnail_url": figma_data.get("thumbnailUrl"),  # Pre-generated, no extra API call
                "registry_path": str(registry_path),
            }
            
        except Exception as e:
            logger.error(f"❌ Conversion failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }
    
    def _fetch_file(self, file_id: str) -> Dict:
        """Fetch Figma file with caching and retry logic - ⭐ UPDATED"""
        # Check cache first — use absolute path so it's stable regardless of cwd
        # __file__ is mcp-automation/src/tools/converter.py → .parent×3 = mcp-automation/
        cache_dir = Path(__file__).parent.parent.parent / "figma_cache"
        cache_dir.mkdir(exist_ok=True)
        cache_file = cache_dir / f"{file_id}.json"
        
        # Use cache if exists and is less than 7 days old
        if cache_file.exists():
            cache_age = time.time() - cache_file.stat().st_mtime
            if cache_age < 604800:  # 7 days = 604800 seconds
                logger.info(f"✅ Using cached Figma data (age: {int(cache_age/60)} minutes)")
                print(f"   ✅ Using cached Figma data (saved {int(cache_age/60)} min ago)")
                with open(cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                logger.info(f"Cache expired (age: {int(cache_age/3600)} hours), fetching fresh data")
        
        # Fetch from API with retry logic
        headers = {"X-Figma-Token": self.figma_token}
        url = f"{self.api_base}/files/{file_id}"
        
        max_retries = 3
        retry_delay = 65  # Start with 65 seconds (just over the 60s rate limit window)
        
        for attempt in range(max_retries):
            logger.info(f"📡 Fetching from Figma API (attempt {attempt + 1}/{max_retries})")
            print(f"   📡 Fetching from Figma API (attempt {attempt + 1}/{max_retries})...")
            
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                # Success! Cache it
                data = response.json()
                
                # Save to cache
                with open(cache_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f)
                logger.info(f"✅ Fetched and cached Figma data")
                print(f"   ✅ Data fetched successfully and cached for future use")
                
                return data
            
            elif response.status_code == 429:
                # Rate limit hit!
                if attempt < max_retries - 1:
                    logger.warning(f"⏰ Rate limit hit! Waiting {retry_delay} seconds...")
                    print(f"\n   ⏰ Figma API rate limit reached!")
                    print(f"   ⏳ Auto-waiting {retry_delay} seconds before retry...")
                    print(f"   💡 Tip: After this succeeds, future calls will use cache (no rate limit!)")
                    
                    # Countdown timer (in 10-second intervals)
                    for remaining in range(retry_delay, 0, -10):
                        if remaining > 10:
                            print(f"      ⏱️  {remaining} seconds remaining...")
                            time.sleep(10)
                        else:
                            print(f"      ⏱️  {remaining} seconds remaining...")
                            time.sleep(remaining)
                            break
                    
                    print(f"   ✅ Wait complete, retrying now...\n")
                    retry_delay *= 2  # Exponential backoff (65s, 130s, 260s)
                    continue
                else:
                    raise Exception(
                        f"⏰ Figma API rate limit exceeded after {max_retries} attempts.\n\n"
                        f"💡 SOLUTIONS:\n"
                        f"   1. Wait 5 minutes and try again (clears rate limit)\n"
                        f"   2. Use a different Figma file for testing\n"
                        f"   3. Upgrade to Figma Pro for higher rate limits\n\n"
                        f"📊 Rate Limits:\n"
                        f"   - Free: 2 requests per minute\n"
                        f"   - Pro: 10 requests per minute\n"
                        f"   - Team: 100 requests per minute"
                    )
            
            else:
                # Other HTTP error
                raise Exception(f"Failed to fetch Figma file: {response.text}")
        
        raise Exception("Max retries exceeded")
    
    def _get_frames(self, root: FigmaNode) -> List[FigmaNode]:
        """Get all top-level frames"""
        frames = []
        
        # Look in all pages
        for page in root.children:
            for child in page.children:
                if child.type == "FRAME" and child.visible:
                    frames.append(child)
        
        return frames
    
    def _extract_file_id(self, url: str) -> str:
        """Extract file ID from Figma URL"""
        patterns = [
            r'/design/([a-zA-Z0-9]+)',
            r'/file/([a-zA-Z0-9]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        raise Exception("Invalid Figma URL")
    
    def _sanitize_name(self, name: str) -> str:
        """Convert to valid component name"""
        name = re.sub(r'[^a-zA-Z0-9\s]', '', name)
        words = name.split()
        return ''.join(word.capitalize() for word in words) or "Component"
    
    def _generate_nextjs_structure(self, output_dir: Path, components: List[Dict]):
        """Generate complete Next.js App Router structure"""
        # Create src/app directory
        app_dir = output_dir / "src" / "app"
        app_dir.mkdir(parents=True, exist_ok=True)

        # Generate globals.css with Tailwind directives
        globals_css = '''@tailwind base;
@tailwind components;
@tailwind utilities;

html,
body {
  margin: 0;
  padding: 0;
  height: 100%;
  overflow: hidden;
}
'''
        with open(app_dir / "globals.css", "w", encoding="utf-8") as f:
            f.write(globals_css)

        # Generate layout.tsx
        layout_code = '''import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import './globals.css'

const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: 'Generated from Figma - GodComet',
  description: 'Figma to Code by GodComet',
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
'''
        with open(app_dir / "layout.tsx", "w", encoding="utf-8") as f:
            f.write(layout_code)

        # Generate page.tsx that imports all components
        imports = "\n".join([
            f"import {c['name']} from '@/components/{c['name']}'"
            for c in components
        ])

        renders = "\n        ".join([f"<{c['name']} />" for c in components])

        page_code = f'''{imports}

export default function Home() {{
  return (
    <>
      {renders}
    </>
  )
}}
'''
        with open(app_dir / "page.tsx", "w", encoding="utf-8") as f:
            f.write(page_code)

        # Ensure src/components exists (should already exist from convert())
        src_components = output_dir / "src" / "components"
        src_components.mkdir(parents=True, exist_ok=True)
    
    def _generate_package_json(self, output_dir: Path):
        """Generate package.json"""
        pkg = {
            "name": "figma-to-code",
            "version": "1.0.0",
            "scripts": {
                "dev": "next dev",
                "build": "next build",
                "start": "next start"
            },
            "dependencies": {
                "react": "^18.2.0",
                "react-dom": "^18.2.0",
                "next": "^14.0.0"
            },
            "devDependencies": {
                "tailwindcss": "^3.4.0",
                "autoprefixer": "^10.4.0",
                "postcss": "^8.4.0",
                "typescript": "^5.3.0",
                "@types/react": "^18.2.0",
                "@types/node": "^20.10.0"
            }
        }
        
        with open(output_dir / "package.json", "w") as f:
            json.dump(pkg, f, indent=2)
    
    def _generate_tailwind_config(self, output_dir: Path):
        """Generate tailwind.config.js with correct content paths"""
        config = '''/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './src/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}
'''
        with open(output_dir / "tailwind.config.js", "w", encoding="utf-8") as f:
            f.write(config)

    def _generate_postcss_config(self, output_dir: Path):
        """Generate postcss.config.js"""
        config = '''module.exports = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
'''
        with open(output_dir / "postcss.config.js", "w", encoding="utf-8") as f:
            f.write(config)

    def _generate_next_config(self, output_dir: Path):
        """Generate next.config.js with static export for fast local rendering"""
        config = '''/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',   // Generates static HTML in out/ — enables fast file:// preview
  images: {
    unoptimized: true, // Required for static export with next/image
  },
}

module.exports = nextConfig
'''
        with open(output_dir / "next.config.js", "w", encoding="utf-8") as f:
            f.write(config)

    def _generate_tsconfig(self, output_dir: Path):
        """Generate tsconfig.json"""
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
                "paths": {
                    "@/*": ["./src/*"]
                }
            },
            "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
            "exclude": ["node_modules"]
        }
        with open(output_dir / "tsconfig.json", "w", encoding="utf-8") as f:
            json.dump(tsconfig, f, indent=2)

    def _generate_gitignore(self, output_dir: Path):
        """Generate .gitignore"""
        gitignore = '''node_modules/
.next/
out/
.env
.env.local
*.tsbuildinfo
'''
        with open(output_dir / ".gitignore", "w", encoding="utf-8") as f:
            f.write(gitignore)
    
    def _write_component_registry(
        self,
        output_dir: Path,
        file_id: str,
        file_name: str,
        generated: List[Dict],
    ) -> Path:
        """
        Write component_registry.json to the project root.

        Merges with any existing registry:
          - Updates entries whose code changed (new hash → new last_updated)
          - Preserves last_updated for unchanged entries
          - Adds entries for newly generated components
          - Removes entries for Figma nodes no longer in this run
        """
        now = datetime.now(timezone.utc).isoformat()
        registry_path = output_dir / "component_registry.json"

        # Load existing registry for merge
        existing: Dict = {}
        if registry_path.exists():
            try:
                with open(registry_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = {}

        def md5_file(path: Path) -> str:
            if not path.exists():
                return ""
            return hashlib.md5(path.read_bytes()).hexdigest()

        def parse_local_imports(path: Path) -> List[str]:
            """Return sorted list of local src/components/*.tsx paths imported by this file."""
            if not path.exists():
                return []
            text = path.read_text(encoding="utf-8")
            deps = []
            for m in re.finditer(
                r"from\s+['\"](?:@/|\.\./)components/([^'\"]+)['\"]", text
            ):
                comp_name = m.group(1)
                for ext in (".tsx", ".ts", ".jsx", ".js"):
                    if comp_name.endswith(ext):
                        comp_name = comp_name[: -len(ext)]
                        break
                deps.append(f"src/components/{comp_name}.tsx")
            return sorted(set(deps))

        # Current node ID set — used to prune stale entries from a previous run
        current_node_ids = {g["node_id"] for g in generated if g.get("node_id")}

        # ── Components ─────────────────────────────────────────────────────────
        existing_components: Dict = existing.get("components", {})
        # Drop entries whose Figma node no longer exists
        pruned: Dict = {
            k: v for k, v in existing_components.items() if k in current_node_ids
        }

        for g in generated:
            node_id = g.get("node_id", "")
            file_abs = Path(g["file"])
            rel_path = file_abs.relative_to(output_dir).as_posix()
            file_hash = md5_file(file_abs)
            deps = parse_local_imports(file_abs)

            if node_id in pruned:
                old = pruned[node_id]
                pruned[node_id] = {
                    "name": g["name"],
                    "file_path": rel_path,
                    "figma_node_type": g.get("node_type", "FRAME"),
                    "code_hash": file_hash,
                    # Preserve original timestamp when file is unchanged
                    "last_updated": now if file_hash != old.get("code_hash") else old.get("last_updated", now),
                    "dependencies": deps,
                }
            else:
                pruned[node_id] = {
                    "name": g["name"],
                    "file_path": rel_path,
                    "figma_node_type": g.get("node_type", "FRAME"),
                    "code_hash": file_hash,
                    "last_updated": now,
                    "dependencies": deps,
                }

        # ── Pages ──────────────────────────────────────────────────────────────
        # src/app/page.tsx is generated from all frames so it has no single
        # Figma frame ID — use the stable key "root_page".
        page_file = output_dir / "src" / "app" / "page.tsx"
        page_hash = md5_file(page_file)
        page_deps = parse_local_imports(page_file)
        existing_pages: Dict = existing.get("pages", {})
        old_page = existing_pages.get("root_page", {})
        pages = {
            "root_page": {
                "name": "Home",
                "file_path": "src/app/page.tsx",
                "code_hash": page_hash,
                "last_updated": now if page_hash != old_page.get("code_hash") else old_page.get("last_updated", now),
                "dependencies": page_deps,
            }
        }

        # ── Assemble and write ─────────────────────────────────────────────────
        registry = {
            "generated_at": now,
            "figma_file_id": file_id,
            "figma_file_name": file_name,
            "components": pruned,
            "pages": pages,
        }

        with open(registry_path, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2)

        logger.info(
            f"📋 Registry: {len(pruned)} component(s), {len(pages)} page(s) → {registry_path.name}"
        )
        return registry_path

    def _generate_readme(self, output_dir: Path, figma_url: str):
        """Generate README"""
        readme = f'''# Figma to Code - Production Ready

Generated from: {figma_url}

## Features

- Auto-layout to Flexbox/Grid
- Responsive design (Tailwind breakpoints)
- Component extraction
- Image optimization
- Production-ready React + Tailwind
- Next.js ready

## Setup

```bash
npm install
npm run dev
```

Open http://localhost:3000

## What's Included

- React components with Tailwind CSS
- Responsive layout (flexbox/grid)
- Optimized images
- Production-ready code
- No inline styles!

Built with advanced Figma API parsing
'''
        
        with open(output_dir / "README.md", "w", encoding="utf-8") as f:
            f.write(readme)


# Main function
async def convert_figma(figma_url: str, figma_token: str, output_path: str):
    """Convert Figma to production code"""
    converter = ProductionFigmaToCode(figma_token)
    result = await converter.convert(figma_url, Path(output_path))
    return result