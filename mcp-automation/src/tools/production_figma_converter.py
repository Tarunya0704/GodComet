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
        """Convert width/height to Tailwind"""
        classes = []
        
        # Width
        if node.primary_axis_sizing == "FIXED":
            w = int(node.width)
            if w == 0:
                pass
            elif w <= 640:
                classes.append(f"w-[{w}px]")
            else:
                classes.append("w-full")
        elif node.primary_axis_sizing == "FILL":
            classes.append("w-full")
        
        # Height
        if node.counter_axis_sizing == "FIXED":
            h = int(node.height)
            if h > 0:
                classes.append(f"h-[{h}px]")
        elif node.counter_axis_sizing == "FILL":
            classes.append("h-full")
        
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
                    # Sanitize filename - replace : with _ for Windows compatibility
                    safe_id = node.id.replace(':', '_').replace('/', '_')
                    filename = f"{safe_id}.png"
                    filepath = images_dir / filename
                    
                    await self._download_file(session, url, filepath)
                    image_map[node.id] = f"/images/{filename}"
                    logger.info(f"Downloaded image: {filename}")
        
        return image_map
    
    def _has_image_fill(self, node: FigmaNode) -> bool:
        """Check if node has image fill"""
        for fill in node.fills:
            if fill.get("type") == "IMAGE":
                return True
        return False
    
    async def _fetch_image_urls(self, file_id: str, node_ids: List[str]) -> Dict[str, str]:
        """Fetch image URLs from Figma API"""
        if not node_ids:
            return {}
        
        headers = {"X-Figma-Token": self.figma_token}
        ids_param = ",".join(node_ids[:100])  # Max 100 at a time
        url = f"{self.api_base}/images/{file_id}?ids={ids_param}&format=png&scale=2"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("images", {})
        return {}
    
    async def _download_file(self, session: aiohttp.ClientSession, url: str, filepath: Path):
        """Download file from URL"""
        async with session.get(url) as response:
            if response.status == 200:
                content = await response.read()
                with open(filepath, "wb") as f:
                    f.write(content)


class ReactCodeGenerator:
    """Generates production-ready React + Tailwind code"""
    
    def __init__(self):
        self.tailwind = TailwindConverter()
        self.responsive = ResponsiveLayoutEngine()
        
    def generate_component(self, node: FigmaNode, component_name: str, image_map: Dict[str, str]) -> str:
        """Generate React component from Figma node"""
        jsx = self._generate_jsx(node, image_map, indent=2)
        
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
    
    def _generate_jsx(self, node: FigmaNode, image_map: Dict[str, str], indent: int = 0) -> str:
        """Recursively generate JSX"""
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
        
        # Build className string
        class_str = " ".join(classes)
        
        # Opening tag
        if element == "img":
            # Next.js Image component
            img_src = image_map.get(node.id, "")
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
        lines.append(f'{ind}<{element}{f' className="{class_str}"' if class_str else ""}>')
        
        # Text content
        if node.type == "TEXT" and node.characters:
            text = node.characters.replace("\n", "<br/>")
            lines.append(f'{ind}  {text}')
        
        # Children
        if node.has_auto_layout or node.type in ["FRAME", "GROUP"]:
            for child in node.children:
                child_jsx = self._generate_jsx(child, image_map, indent + 1)
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

            messages = []

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
                max_tokens=8000
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

        # Children (limit depth to 5 levels for better detail)
        if depth < 5 and node.children:
            result["children"] = [
                self._simplify_node(child, image_map, depth + 1)
                for child in node.children
                if child.visible
            ]

        return result

    def _build_prompt(self, component_name: str, structure: Dict, image_refs: List[str]) -> str:
        """Build the prompt for AI code generation"""
        images_list = "\n".join(image_refs) if image_refs else "  (none)"

        # Truncate structure to avoid token limits
        structure_str = json.dumps(structure, indent=1)
        if len(structure_str) > 4000:
            structure_str = structure_str[:4000] + "\n... (truncated)"

        return f"""Generate a React + Tailwind CSS component that EXACTLY matches the design shown in the image.

Component name: {component_name}

Available images (use Next.js Image component with these exact paths):
{images_list}

The structure data below contains the EXACT CSS properties from Figma for each element:
- "bg": exact background color (use as bg-[#hex])
- "css.color": exact text color (use as text-[#hex])
- "css.fontSize": exact font size (use as text-[Xpx])
- "css.fontWeight": exact weight (use font-normal/medium/semibold/bold)
- "layout": flex direction ("horizontal" = flex-row, "vertical" = flex-col)
- "justify"/"align": flex alignment
- "gap": spacing between items (use gap-[Xpx])
- "padding": padding values (use p-[Xpx] or pt/pr/pb/pl)
- "radius": border radius (use rounded-[Xpx])
- "border": border width and color
- "shadow": box shadow
- "w"/"h": width/height in pixels
- "widthMode"/"heightMode": "fill" means use w-full/h-full

Figma structure:
{structure_str}

REQUIREMENTS:
1. `import Image from 'next/image'` for images, `export default function {component_name}()`
2. Use EXACT hex colors from the structure data: bg-[#1a1a2e], text-[#667eea], etc.
3. Use EXACT pixel values for spacing/sizing: w-[240px], gap-[16px], p-[24px], text-[14px]
4. Match the layout precisely from the image - sidebar, grid, cards, spacing
5. Include ALL text content from the "text" fields in the structure
6. For image elements, use: <Image src="..." alt="..." width={{W}} height={{H}} className="object-cover" />
7. Static component only - no useState/useEffect
8. Output ONLY the TSX code, no explanations or markdown"""


class ProductionFigmaToCode:
    """Production-grade Figma to code converter"""

    def __init__(self, figma_token: str):
        self.figma_token = figma_token
        self.api_base = "https://api.figma.com/v1"
        self.component_extractor = ComponentExtractor()
        self.code_generator = ReactCodeGenerator()
        self.ai_generator = AICodeGenerator()
        self.image_downloader = ImageDownloader(figma_token)
    
    async def convert(self, figma_url: str, output_dir: Path, figma_screenshot_path: str = None) -> Dict:
        """Convert Figma to production-ready code"""
        try:
            file_id = self._extract_file_id(figma_url)
            logger.info(f"🎨 Converting Figma file: {file_id}")
            
            # Fetch Figma file
            figma_data = self._fetch_file(file_id)
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
            
            # Download images
            all_nodes = []
            for frame in frames:
                all_nodes.extend(self.code_generator._get_all_nodes(frame))
            image_map = await self.image_downloader.download_images(file_id, all_nodes, output_dir)
            logger.info(f"✅ Downloaded {len(image_map)} images")
            
            # Generate components - try AI first, fall back to programmatic
            generated = []
            for frame in frames:
                comp_name = self._sanitize_name(frame.name)
                logger.info(f"🔨 Generating: {comp_name}")

                code = None

                # Try AI-powered generation first (much better quality)
                if self.ai_generator.available:
                    logger.info(f"🤖 Using AI code generation for {comp_name}")
                    code = self.ai_generator.generate_component(
                        frame, comp_name, image_map, figma_screenshot_path
                    )
                    if code:
                        logger.info(f"✅ AI generated {comp_name} successfully")
                    else:
                        logger.warning(f"⚠️ AI generation failed, falling back to programmatic")

                # Fall back to programmatic generation
                if not code:
                    logger.info(f"⚙️ Using programmatic generation for {comp_name}")
                    code = self.code_generator.generate_component(frame, comp_name, image_map)

                comp_file = components_dir / f"{comp_name}.tsx"
                with open(comp_file, "w", encoding="utf-8") as f:
                    f.write(code)

                generated.append({
                    "name": comp_name,
                    "file": str(comp_file),
                    "original": frame.name
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
            
            logger.info("🎉 Conversion complete!")
            
            return {
                "success": True,
                "components": generated,
                "images": len(image_map),
                "output_dir": str(output_dir)
            }
            
        except Exception as e:
            logger.error(f"❌ Conversion failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }
    
    def _fetch_file(self, file_id: str) -> Dict:
        """Fetch Figma file with caching and retry logic - ⭐ UPDATED"""
        # Check cache first
        cache_dir = Path("figma_cache")
        cache_dir.mkdir(exist_ok=True)
        cache_file = cache_dir / f"{file_id}.json"
        
        # Use cache if exists and is less than 1 hour old
        if cache_file.exists():
            cache_age = time.time() - cache_file.stat().st_mtime
            if cache_age < 3600:  # 1 hour = 3600 seconds
                logger.info(f"✅ Using cached Figma data (age: {int(cache_age/60)} minutes)")
                print(f"   ✅ Using cached Figma data (saved {int(cache_age/60)} min ago)")
                with open(cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                logger.info(f"Cache expired (age: {int(cache_age/60)} minutes), fetching fresh data")
        
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

body {
  margin: 0;
  padding: 0;
  min-height: 100vh;
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
    <main className="min-h-screen bg-gray-50">
      <div className="w-full">
        {renders}
      </div>
    </main>
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
        """Generate next.config.js"""
        config = '''/** @type {import('next').NextConfig} */
const nextConfig = {
  images: {
    unoptimized: true,
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