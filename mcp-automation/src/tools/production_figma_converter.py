"""
PRODUCTION-GRADE FIGMA TO CODE CONVERTER
Handles: Auto-layout, Components, Responsive, Images, Tailwind, Component extraction
UPDATED: Added caching + auto-retry for rate limit handling
"""
import os
import json
import subprocess
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
        self.layout_positioning = data.get("layoutPositioning", "AUTO")  # "ABSOLUTE" = explicitly absolute within auto-layout parent
        self.constraints = data.get("constraints", {})

        # How this node sizes WITHIN its auto-layout parent (Figma API v2+).
        # "FIXED" = exact pixel size, "FILL" = flex-1 / h-full, "HUG" = shrink to content.
        # Defaults to "FIXED" so old designs (no field) keep their absolute bounding-box width.
        self.layout_sizing_h = data.get("layoutSizingHorizontal", "FIXED")
        self.layout_sizing_v = data.get("layoutSizingVertical",   "FIXED")
        
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
        
        # Visual properties — MCP YAML parser can return fills/strokes as a string
        # instead of a list of dicts. Always normalise to List[dict] so every
        # downstream caller can safely call fill.get() without an isinstance guard.
        _raw_fills = data.get("fills", [])
        self.fills: List[Dict] = (
            [f for f in _raw_fills if isinstance(f, dict)]
            if isinstance(_raw_fills, list) else []
        )
        _raw_strokes = data.get("strokes", [])
        self.strokes: List[Dict] = (
            [s for s in _raw_strokes if isinstance(s, dict)]
            if isinstance(_raw_strokes, list) else []
        )
        _raw_effects = data.get("effects", [])
        self.effects: List[Dict] = (
            [e for e in _raw_effects if isinstance(e, dict)]
            if isinstance(_raw_effects, list) else []
        )
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


class DesignTokenExtractor:
    """Walks the entire Figma document tree and extracts a reusable design-token layer.

    Collected values are deduplicated, ranked by frequency, and assigned semantic
    names (primary, surface, text.secondary …) based on colour-luminance bucketing
    and value ordering — nothing is hardcoded for a specific design.

    Call extract(root) then write_tokens_file(output_dir) to write
    src/tokens.ts into the generated Next.js project.
    """

    _SPACING_NAMES  = ["xs", "sm", "md", "lg", "xl", "2xl", "3xl"]
    _RADIUS_NAMES   = ["sm", "md", "lg", "xl", "2xl"]
    _SHADOW_NAMES   = ["sm", "md", "lg", "xl"]
    _TYPE_NAMES     = ["display", "h1", "h2", "h3", "h4", "body", "sm", "xs", "caption"]

    def __init__(self):
        self._colors:      Dict[str, int]  = {}   # hex  -> frequency
        self._font_sizes:  Dict[int, int]  = {}   # px   -> frequency
        self._font_weights:Dict[int, int]  = {}   # num  -> frequency
        self._line_heights:Dict[int, int]  = {}   # px   -> frequency
        self._spacings:    Dict[int, int]  = {}   # px   -> frequency
        self._radii:       Dict[int, int]  = {}   # px   -> frequency
        self._shadows:     List[str]       = []   # deduplicated CSS strings

    # ── Public API ───────────────────────────────────────────────────────────

    def extract(self, root: FigmaNode) -> None:
        """Walk the entire Figma tree and collect all design values."""
        self._walk(root)

    def build_tokens(self) -> Dict:
        """Return a structured token dict ready to be serialised."""
        return {
            "colors":     self._build_color_tokens(),
            "spacing":    self._build_scale_tokens(self._spacings, min_v=2, max_v=120, names=self._SPACING_NAMES),
            "typography": self._build_typography_tokens(),
            "radii":      self._build_radii_tokens(),
            "shadows":    self._build_shadow_tokens(),
        }

    @staticmethod
    def _safe_key(key: str) -> str:
        """Prefix keys that start with a digit so they are valid TS identifiers."""
        return f"sz{key}" if key and key[0].isdigit() else key

    def write_tokens_file(self, output_dir: Path) -> Path:
        """Serialise tokens to src/tokens.ts and return the path."""
        tokens = self.build_tokens()
        lines: List[str] = [
            "// Auto-generated design tokens — re-generated on every Figma export.",
            "// Edit the Figma file, not this file.",
            "",
            "export const tokens = {",
        ]

        sk = self._safe_key

        # colors
        lines.append("  colors: {")
        for key, val in tokens["colors"].items():
            if isinstance(val, dict):
                lines.append(f"    {sk(key)}: {{")
                for k, v in val.items():
                    lines.append(f"      {sk(k)}: '{v}',")
                lines.append("    },")
            else:
                lines.append(f"    {sk(key)}: '{val}',")
        lines.append("  },")

        # spacing
        lines.append("  spacing: {")
        for key, val in tokens["spacing"].items():
            lines.append(f"    {sk(key)}: {val},")
        lines.append("  },")

        # typography
        lines.append("  typography: {")
        for key, val in tokens["typography"].items():
            size   = val.get("size", 16)
            weight = val.get("weight", 400)
            lh     = val.get("lineHeight", "")
            lh_str = f", lineHeight: {lh}" if lh else ""
            lines.append(f"    {sk(key)}: {{ size: {size}, weight: {weight}{lh_str} }},")
        lines.append("  },")

        # radii
        lines.append("  radii: {")
        for key, val in tokens["radii"].items():
            lines.append(f"    {sk(key)}: {val},")
        lines.append("  },")

        # shadows
        if tokens["shadows"]:
            lines.append("  shadows: {")
            for key, val in tokens["shadows"].items():
                lines.append(f"    {sk(key)}: '{val}',")
            lines.append("  },")

        lines += ["} as const", "", "export type Tokens = typeof tokens", ""]

        tokens_path = output_dir / "src" / "tokens.ts"
        tokens_path.parent.mkdir(parents=True, exist_ok=True)
        tokens_path.write_text("\n".join(lines), encoding="utf-8")

        logger.info(
            f"🎨 Design tokens written: tokens.ts "
            f"({len(tokens['colors'])} colors, "
            f"{len(tokens['spacing'])} spacings, "
            f"{len(tokens['typography'])} type styles, "
            f"{len(tokens['radii'])} radii)"
        )
        return tokens_path

    # ── Tree walker ──────────────────────────────────────────────────────────

    def _walk(self, node: FigmaNode) -> None:
        self._collect_colors(node)
        self._collect_typography(node)
        self._collect_spacing(node)
        self._collect_radii(node)
        self._collect_shadows(node)
        for child in node.children:
            self._walk(child)

    # ── Collectors ───────────────────────────────────────────────────────────

    def _collect_colors(self, node: FigmaNode) -> None:
        for fill in node.fills:
            if fill.get("type") == "SOLID" and fill.get("visible", True):
                h = self._rgba_to_hex(fill["color"])
                if h:
                    self._colors[h] = self._colors.get(h, 0) + 1
        for stroke in node.strokes:
            if stroke.get("type") == "SOLID" and stroke.get("visible", True):
                h = self._rgba_to_hex(stroke["color"])
                if h:
                    self._colors[h] = self._colors.get(h, 0) + 1

    def _collect_typography(self, node: FigmaNode) -> None:
        if node.type != "TEXT":
            return
        s = node.style
        size = int(s.get("fontSize", 0))
        if size > 0:
            self._font_sizes[size] = self._font_sizes.get(size, 0) + 1
        weight = int(s.get("fontWeight", 400))
        self._font_weights[weight] = self._font_weights.get(weight, 0) + 1
        lh = s.get("lineHeightPx")
        if lh and lh > 0:
            lh_int = int(round(lh))
            self._line_heights[lh_int] = self._line_heights.get(lh_int, 0) + 1

    def _collect_spacing(self, node: FigmaNode) -> None:
        for v in node.padding.values():
            if v > 0:
                iv = int(v)
                self._spacings[iv] = self._spacings.get(iv, 0) + 1
        if node.item_spacing > 0:
            iv = int(node.item_spacing)
            self._spacings[iv] = self._spacings.get(iv, 0) + 1

    def _collect_radii(self, node: FigmaNode) -> None:
        r = node.corner_radius
        if 0 < r < 9000:
            ir = int(round(r))
            self._radii[ir] = self._radii.get(ir, 0) + 1

    def _collect_shadows(self, node: FigmaNode) -> None:
        for effect in node.effects:
            if effect.get("type") != "DROP_SHADOW" or not effect.get("visible", True):
                continue
            c      = effect.get("color", {})
            r, g, b = int(c.get("r", 0) * 255), int(c.get("g", 0) * 255), int(c.get("b", 0) * 255)
            a      = round(float(c.get("a", 0.4)), 2)
            off    = effect.get("offset", {})
            x, y   = int(off.get("x", 0)), int(off.get("y", 4))
            blur   = int(effect.get("radius", 8))
            spread = int(effect.get("spread", 0))
            spread_part = f" {spread}px" if spread else ""
            css    = f"{x}px {y}px {blur}px{spread_part} rgba({r},{g},{b},{a})"
            if css not in self._shadows:
                self._shadows.append(css)

    # ── Token builders ───────────────────────────────────────────────────────

    @staticmethod
    def _luminance(hex_val: str) -> float:
        r = int(hex_val[1:3], 16) / 255
        g = int(hex_val[3:5], 16) / 255
        b = int(hex_val[5:7], 16) / 255
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    @staticmethod
    def _rgba_to_hex(color: Dict) -> Optional[str]:
        try:
            r = int(color["r"] * 255)
            g = int(color["g"] * 255)
            b = int(color["b"] * 255)
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return None

    def _build_color_tokens(self) -> Dict:
        if not self._colors:
            return {}

        # Bucket by luminance: very-dark → backgrounds, mid → accents, very-light → text
        sorted_by_freq = sorted(self._colors.items(), key=lambda x: -x[1])

        backgrounds: List[str] = []
        surfaces:    List[str] = []
        accents:     List[str] = []
        lights:      List[str] = []

        for hex_val, _ in sorted_by_freq:
            lum = self._luminance(hex_val)
            if lum < 0.08:
                backgrounds.append(hex_val)
            elif lum < 0.25:
                surfaces.append(hex_val)
            elif lum < 0.65:
                accents.append(hex_val)
            else:
                lights.append(hex_val)

        tokens: Dict = {}
        bg_keys     = ["background", "surface", "overlay"]
        accent_keys = ["primary", "secondary", "tertiary", "accent", "highlight", "link"]
        text_keys   = ["primary", "secondary", "muted"]

        for i, h in enumerate(backgrounds[:3]):
            tokens[bg_keys[i]] = h
        for i, h in enumerate(surfaces[:2]):
            if surfaces and bg_keys[i + 1] not in tokens:
                tokens[bg_keys[i + 1]] = h

        for i, h in enumerate(accents[:6]):
            tokens[accent_keys[i]] = h

        text_dict: Dict[str, str] = {}
        for i, h in enumerate(lights[:3]):
            text_dict[text_keys[i]] = h
        if text_dict:
            tokens["text"] = text_dict

        return tokens

    def _build_scale_tokens(
        self,
        freq_map: Dict[int, int],
        min_v: int,
        max_v: int,
        names: List[str],
    ) -> Dict[str, int]:
        candidates = sorted(
            [(v, f) for v, f in freq_map.items() if min_v <= v <= max_v],
            key=lambda x: -x[1],
        )
        top = sorted([v for v, _ in candidates[: len(names)]])
        return {names[i]: v for i, v in enumerate(top)}

    def _build_typography_tokens(self) -> Dict:
        sizes = sorted(self._font_sizes.keys(), reverse=True)
        result: Dict = {}
        for i, size in enumerate(sizes[: len(self._TYPE_NAMES)]):
            name   = self._TYPE_NAMES[i]
            # Use the most frequent weight; fall back to 400
            weight = max(self._font_weights, key=lambda w: self._font_weights[w], default=400)
            entry: Dict = {"size": size, "weight": weight}
            # Attach a matching line-height if one was observed close to size * 1.3
            candidates = [lh for lh in self._line_heights if abs(lh - size * 1.3) < size * 0.3]
            if candidates:
                entry["lineHeight"] = min(candidates, key=lambda lh: abs(lh - size * 1.3))
            result[name] = entry
        return result

    def _build_radii_tokens(self) -> Dict[str, int]:
        tokens: Dict[str, int] = {}
        sorted_radii = sorted(self._radii.keys())
        for i, r in enumerate(sorted_radii[: len(self._RADIUS_NAMES)]):
            tokens[self._RADIUS_NAMES[i]] = r
        tokens["full"] = 9999
        return tokens

    def _build_shadow_tokens(self) -> Dict[str, str]:
        return {
            self._SHADOW_NAMES[i]: css
            for i, css in enumerate(self._shadows[: len(self._SHADOW_NAMES)])
        }


class ComponentClassifier:
    """Classifies any FigmaNode into a semantic component type.

    Priority order:
      1. Component/Instance name keywords
      2. Dimension + structural heuristics
      3. Fallback → "Generic"
    """

    _KEYWORD_MAP = [
        ({"button"},                                   "Button"),
        ({"input", "field", "textfield"},              "Input"),
        ({"card"},                                     "Card"),
        ({"badge", "chip", "tag"},                     "Badge"),
        ({"avatar", "profile pic"},                    "Avatar"),
        ({"nav", "sidebar", "menu item"},              "NavItem"),
        ({"modal", "dialog", "popup"},                 "Modal"),
        ({"toggle", "switch", "checkbox"},             "Toggle"),
    ]

    def classify(self, node: FigmaNode) -> str:
        """Return the semantic type string for a single node."""
        # ── Rule 1: keyword match on COMPONENT / INSTANCE names ──────────────
        if node.type in ("COMPONENT", "INSTANCE", "COMPONENT_SET"):
            name_lower = node.name.lower()
            for keywords, semantic in self._KEYWORD_MAP:
                if any(kw in name_lower for kw in keywords):
                    return semantic

        # ── Rule 2: dimension / structural heuristics ─────────────────────────
        w, h = node.width, node.height

        # Button: small, wide-ish, solid fill
        if w < 200 and h < 60 and self._has_solid_fill(node):
            return "Button"

        # Avatar: small square with high corner radius
        if w < 60 and h < 60 and node.corner_radius > 20:
            return "Avatar"

        # Card: container with at least one TEXT child and one image-fill child
        if node.children:
            has_text_child  = any(c.type == "TEXT" for c in node.children)
            has_image_child = any(self._has_image_fill(c) for c in node.children)
            if has_text_child and has_image_child:
                return "Card"

        # Badge: narrow short strip
        if w < 120 and h < 32:
            return "Badge"

        # NavItem: tall vertical container with 4+ children
        if h > w * 3 and len(node.children) >= 4:
            return "NavItem"

        return "Generic"

    def classify_tree(self, root: FigmaNode) -> Dict[str, str]:
        """Walk the full tree and return {node_id: semantic_type} for non-Generic nodes."""
        result: Dict[str, str] = {}
        self._walk(root, result)
        return result

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _walk(self, node: FigmaNode, result: Dict[str, str]) -> None:
        semantic = self.classify(node)
        if semantic != "Generic":
            result[node.id] = semantic
        for child in node.children:
            self._walk(child, result)

    @staticmethod
    def _has_solid_fill(node: FigmaNode) -> bool:
        if not isinstance(node.fills, list):
            return False
        return any(isinstance(f, dict) and f.get("type") == "SOLID" and f.get("visible", True) for f in node.fills)

    @staticmethod
    def _has_image_fill(node: FigmaNode) -> bool:
        if not isinstance(node.fills, list):
            return False
        return any(isinstance(f, dict) and f.get("type") == "IMAGE" and f.get("visible", True) for f in node.fills)


class PropBasedGenerator:
    """Generates reusable React UI components with typed props from Figma node measurements.

    Each generator derives colors, sizes, and radii directly from the supplied FigmaNode
    so the output is never hardcoded to a specific design.
    """

    # ── Public entry point ────────────────────────────────────────────────────

    def generate_ui_components(
        self,
        classified: Dict[str, str],
        root: FigmaNode,
        output_dir: Path,
    ) -> List[str]:
        """Write one UI component file per semantic type found in *classified*.

        Only Button, Card, and Badge are handled. For each type the first
        matching node in the tree is used as the style source.
        Returns a list of absolute file paths written.
        """
        ui_dir = output_dir / "src" / "components" / "ui"
        ui_dir.mkdir(parents=True, exist_ok=True)

        # semantic_type → first node that has that type
        type_to_node: Dict[str, FigmaNode] = {}
        for node_id, semantic in classified.items():
            if semantic in ("Button", "Card", "Badge") and semantic not in type_to_node:
                node = self._find_node(root, node_id)
                if node:
                    type_to_node[semantic] = node

        generators = {
            "Button": self.generate_button,
            "Card":   self.generate_card,
            "Badge":  self.generate_badge,
        }

        written: List[str] = []
        for semantic, node in type_to_node.items():
            path = generators[semantic](node, ui_dir)
            written.append(str(path))
        return written

    # ── Component generators ──────────────────────────────────────────────────

    def generate_button(self, node: FigmaNode, ui_dir: Path) -> Path:
        """Write Button.tsx derived from node fills and dimensions."""
        primary_hex   = self._first_solid_hex(node) or "#3b82f6"
        radius        = int(round(node.corner_radius)) if node.corner_radius else 6
        h             = node.height

        default_size  = "sm" if h < 32 else ("lg" if h >= 48 else "md")
        sm_h = max(28, int(h * 0.75)) if default_size != "sm" else int(h)
        md_h = int(h)               if default_size == "md" else int(sm_h * 1.3)
        lg_h = max(48, int(h * 1.25)) if default_size != "lg" else int(h)

        lines = [
            "import React from 'react'",
            "",
            "export type ButtonProps = {",
            "  variant?:   'primary' | 'secondary' | 'ghost'",
            "  size?:      'sm' | 'md' | 'lg'",
            "  children?:  React.ReactNode",
            "  onClick?:   () => void",
            "  disabled?:  boolean",
            "  className?: string",
            "}",
            "",
            "const variantStyles: Record<NonNullable<ButtonProps['variant']>, string> = {",
            f"  primary:   'bg-[{primary_hex}] text-white hover:opacity-90 active:opacity-80',",
            f"  secondary: 'border border-[{primary_hex}] text-[{primary_hex}] bg-transparent hover:bg-[{primary_hex}]/10',",
            f"  ghost:     'bg-transparent text-[{primary_hex}] hover:bg-[{primary_hex}]/10',",
            "}",
            "",
            "const sizeStyles: Record<NonNullable<ButtonProps['size']>, string> = {",
            f"  sm: 'h-[{sm_h}px] px-3 text-sm   rounded-[{radius}px]',",
            f"  md: 'h-[{md_h}px] px-4 text-base  rounded-[{radius}px]',",
            f"  lg: 'h-[{lg_h}px] px-6 text-lg    rounded-[{radius}px]',",
            "}",
            "",
            "export default function Button({",
            "  variant   = 'primary',",
            "  size      = 'md',",
            "  children,",
            "  onClick,",
            "  disabled  = false,",
            "  className = '',",
            "}: ButtonProps) {",
            "  return (",
            "    <button",
            "      type=\"button\"",
            "      onClick={onClick}",
            "      disabled={disabled}",
            "      className={`inline-flex items-center justify-center font-medium",
            "        transition-opacity select-none",
            "        ${variantStyles[variant]} ${sizeStyles[size]}",
            "        ${disabled ? 'opacity-50 cursor-not-allowed pointer-events-none' : ''}",
            "        ${className}`}",
            "    >",
            "      {children}",
            "    </button>",
            "  )",
            "}",
            "",
        ]

        path = ui_dir / "Button.tsx"
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def generate_card(self, node: FigmaNode, ui_dir: Path) -> Path:
        """Write Card.tsx derived from node background, radius, padding, and shadow."""
        bg_hex  = self._first_solid_hex(node) or "#ffffff"
        radius  = int(round(node.corner_radius)) if node.corner_radius else 8
        pad_t   = int(node.padding.get("top",    16))
        pad_r   = int(node.padding.get("right",  16))
        pad_b   = int(node.padding.get("bottom", 16))
        pad_l   = int(node.padding.get("left",   16))
        padding = f"pt-[{pad_t}px] pr-[{pad_r}px] pb-[{pad_b}px] pl-[{pad_l}px]"
        img_h   = max(120, int(node.height * 0.45))
        img_r   = max(0, radius - 2)

        has_shadow = any(
            e.get("type") == "DROP_SHADOW" and e.get("visible", True)
            for e in node.effects
        )
        hover_cls = (
            "cursor-pointer hover:shadow-lg hover:-translate-y-0.5 transition-all duration-200"
            if has_shadow else ""
        )

        lines = [
            "import React from 'react'",
            "import Image from 'next/image'",
            "",
            "export type CardProps = {",
            "  image?:     string",
            "  title?:     string",
            "  subtitle?:  string",
            "  badge?:     string",
            "  onClick?:   () => void",
            "  className?: string",
            "  children?:  React.ReactNode",
            "}",
            "",
            "export default function Card({",
            "  image,",
            "  title,",
            "  subtitle,",
            "  badge,",
            "  onClick,",
            "  className = '',",
            "  children,",
            "}: CardProps) {",
            "  return (",
            "    <div",
            "      onClick={onClick}",
            f"      className={{`bg-[{bg_hex}] rounded-[{radius}px] {padding} {hover_cls} ${{className}}`}}",
            "    >",
            "      {image && (",
            f"        <div className=\"relative w-full h-[{img_h}px] overflow-hidden rounded-[{img_r}px] mb-3\">",
            "          <Image src={image} fill className=\"object-cover\" alt={title ?? ''} />",
            "        </div>",
            "      )}",
            f"      {{badge && <span className=\"inline-block mb-2 px-2 py-0.5 text-xs font-medium bg-[{bg_hex}]/50 rounded-[{img_r}px]\">{{badge}}</span>}}",
            "      {title    && <h3 className=\"font-semibold text-base mb-1\">{title}</h3>}",
            "      {subtitle && <p  className=\"text-sm opacity-70\">{subtitle}</p>}",
            "      {children}",
            "    </div>",
            "  )",
            "}",
            "",
        ]

        path = ui_dir / "Card.tsx"
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def generate_badge(self, node: FigmaNode, ui_dir: Path) -> Path:
        """Write Badge.tsx derived from node fill color and corner radius."""
        bg_hex   = self._first_solid_hex(node) or "#e5e7eb"
        radius   = int(round(node.corner_radius)) if node.corner_radius else 4
        text_hex = "#ffffff" if self._luminance(bg_hex) < 0.4 else "#1f2937"

        lines = [
            "import React from 'react'",
            "",
            "export type BadgeProps = {",
            "  label:      string",
            "  color?:     'default' | 'primary'",
            "  size?:      'sm' | 'md'",
            "  className?: string",
            "}",
            "",
            "const colorStyles: Record<NonNullable<BadgeProps['color']>, string> = {",
            f"  default: 'bg-[{bg_hex}] text-[{text_hex}]',",
            f"  primary: 'bg-[{bg_hex}] text-[{text_hex}]',",
            "}",
            "",
            "const sizeStyles: Record<NonNullable<BadgeProps['size']>, string> = {",
            f"  sm: 'px-2 py-0.5 text-xs rounded-[{radius}px]',",
            f"  md: 'px-3 py-1   text-sm rounded-[{radius}px]',",
            "}",
            "",
            "export default function Badge({",
            "  label,",
            "  color     = 'default',",
            "  size      = 'md',",
            "  className = '',",
            "}: BadgeProps) {",
            "  return (",
            "    <span",
            "      className={`inline-flex items-center font-medium",
            "        ${colorStyles[color]} ${sizeStyles[size]} ${className}`}",
            "    >",
            "      {label}",
            "    </span>",
            "  )",
            "}",
            "",
        ]

        path = ui_dir / "Badge.tsx"
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _find_node(root: FigmaNode, target_id: str) -> Optional[FigmaNode]:
        """Recursive DFS search for a node by ID."""
        if root.id == target_id:
            return root
        for child in root.children:
            found = PropBasedGenerator._find_node(child, target_id)
            if found:
                return found
        return None

    @staticmethod
    def _first_solid_hex(node: FigmaNode) -> Optional[str]:
        for fill in node.fills:
            if fill.get("type") == "SOLID" and fill.get("visible", True):
                c = fill.get("color", {})
                try:
                    return f"#{int(c['r']*255):02x}{int(c['g']*255):02x}{int(c['b']*255):02x}"
                except Exception:
                    pass
        return None

    @staticmethod
    def _luminance(hex_val: str) -> float:
        r = int(hex_val[1:3], 16) / 255
        g = int(hex_val[3:5], 16) / 255
        b = int(hex_val[5:7], 16) / 255
        return 0.2126 * r + 0.7152 * g + 0.0722 * b


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
            classes.append(TailwindConverter._size_to_tailwind(gap, "gap"))

        # Wrap — Figma: layoutWrap "WRAP" | "NO_WRAP"
        if node.raw.get("layoutWrap") == "WRAP":
            classes.append("flex-wrap")

        return classes
    
    @staticmethod
    def get_spacing_classes(node: FigmaNode) -> List[str]:
        """Convert padding to Tailwind, using the most compact shorthand available.

        Priority:  p-  >  px- py-  >  individual pt- pr- pb- pl-
        """
        classes = []
        t = TailwindConverter._size_to_tailwind

        top    = node.padding["top"]
        right  = node.padding["right"]
        bottom = node.padding["bottom"]
        left   = node.padding["left"]

        if top == right == bottom == left:
            if top > 0:
                classes.append(t(top, "p"))
        elif top == bottom and right == left:
            # px- / py- shorthand
            if top > 0:
                classes.append(t(top, "py"))
            if right > 0:
                classes.append(t(right, "px"))
        else:
            if top    > 0: classes.append(t(top,    "pt"))
            if right  > 0: classes.append(t(right,  "pr"))
            if bottom > 0: classes.append(t(bottom, "pb"))
            if left   > 0: classes.append(t(left,   "pl"))

        return classes
    
    @staticmethod
    def get_sizing_classes(node: FigmaNode, parent: 'FigmaNode' = None) -> List[str]:
        """Convert width/height to Tailwind — respects auto-layout axis direction.

        When *parent* is supplied and has auto-layout, the child's
        layoutSizingHorizontal / layoutSizingVertical fields drive sizing so that
        FILL children become flex-1 / h-full and FIXED children keep their pixel size.

        In Figma:
          HORIZONTAL frame: primary axis = width, counter axis = height
          VERTICAL frame:   primary axis = height, counter axis = width
          No layout:        use actual absolute bounds directly
        """
        classes = []

        # ── Child inside an explicit auto-layout parent ───────────────────────
        # These Figma API v2+ fields tell us exactly how the child should size
        # within the flex container — independently of the child's own content sizing.
        # Exception: if the child is layoutPositioning=ABSOLUTE it is taken OUT of
        # flex flow and must be sized like a non-flex node (primaryAxisSizingMode /
        # absoluteBoundingBox), not by layout_sizing_h/v.
        if (parent is not None
                and parent.has_auto_layout
                and node.layout_positioning != "ABSOLUTE"):
            horiz = parent.layout_mode == "HORIZONTAL"

            # Main axis (width for HORIZONTAL parent, height for VERTICAL parent)
            if horiz:
                if node.layout_sizing_h == "FILL":
                    classes.extend(["flex-1", "min-w-0"])
                elif node.layout_sizing_h == "FIXED":
                    w = int(node.width)
                    if w > 0:
                        classes.append(f"w-[{w}px]")
                # HUG → no width class; shrinks to content
            else:
                if node.layout_sizing_v == "FILL":
                    classes.extend(["flex-1", "min-h-0"])
                elif node.layout_sizing_v == "FIXED":
                    h = int(node.height)
                    if h > 0:
                        classes.append(f"h-[{h}px]")

            # Cross axis (height for HORIZONTAL parent, width for VERTICAL parent)
            if horiz:
                if node.layout_sizing_v == "FILL":
                    classes.append("h-full")
                elif node.layout_sizing_v == "FIXED":
                    h = int(node.height)
                    if h > 0:
                        classes.append(f"h-[{h}px]")
            else:
                if node.layout_sizing_h == "FILL":
                    classes.append("w-full")
                elif node.layout_sizing_h == "FIXED":
                    w = int(node.width)
                    if w > 0:
                        classes.append(f"w-[{w}px]")

            return classes

        if node.layout_mode == "HORIZONTAL":
            # Primary → width
            if node.primary_axis_sizing == "FIXED":
                w = int(node.width)
                if w > 0:
                    classes.append(f"w-[{w}px]")
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
                    classes.append(f"w-[{w}px]")
            elif node.counter_axis_sizing == "FILL":
                classes.append("w-full")

        else:
            # No auto-layout — size from absolute bounding box
            w = int(node.width)
            h = int(node.height)
            if w > 0:
                classes.append(f"w-[{w}px]")
            if h > 0:
                classes.append(f"h-[{h}px]")

        return classes
    
    @staticmethod
    def get_color_classes(node: FigmaNode) -> List[str]:
        """Convert fills/strokes to Tailwind colors"""
        classes = []

        # Background — some node types must NOT get bg-[#hex] from their fills:
        #   TEXT            → fills are text colour, handled by get_text_classes()
        #   VECTOR          → fills are SVG path colours (icon ink), not CSS backgrounds;
        #                     mapping them to bg-[#hex] produces solid black squares
        #   BOOLEAN_OPERATION → same as VECTOR (composed SVG paths)
        _NO_BG_TYPES = {"TEXT", "VECTOR", "BOOLEAN_OPERATION"}
        if node.type not in _NO_BG_TYPES and node.fills and len(node.fills) > 0:
            fill = node.fills[0]
            if fill.get("type") == "SOLID" and fill.get("visible", True):
                color = fill.get("color", {})
                fill_opacity = fill.get("opacity", 1.0)
                bg_class = TailwindConverter._color_to_tailwind(color, "bg", fill_opacity)
                if bg_class:
                    classes.append(bg_class)

        # Border
        if node.strokes and len(node.strokes) > 0:
            stroke = node.strokes[0]
            if stroke.get("type") == "SOLID" and stroke.get("visible", True):
                color = stroke.get("color", {})
                weight = node.raw.get("strokeWeight", 1)
                classes.append(f"border-[{int(weight)}px]")
                stroke_opacity = stroke.get("opacity", 1.0)
                border_class = TailwindConverter._color_to_tailwind(color, "border", stroke_opacity)
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
        
        # Line height — use exact pixel value; only use named classes for exact standard ratios
        line_height = style.get("lineHeightPx")
        lh_unit = style.get("lineHeightUnit", "AUTO")
        if line_height and lh_unit != "AUTO" and size:
            ratio = line_height / size
            named = {1.0: "leading-none", 1.25: "leading-tight", 1.375: "leading-snug",
                     1.5: "leading-normal", 1.625: "leading-relaxed", 2.0: "leading-loose"}
            matched = next((cls for ratio_key, cls in named.items() if abs(ratio - ratio_key) < 0.04), None)
            if matched:
                classes.append(matched)
            else:
                classes.append(f"leading-[{int(round(line_height))}px]")

        # Letter spacing — respect unit: PERCENT means em, PIXELS means px
        letter_spacing = style.get("letterSpacing", 0)
        ls_unit = style.get("letterSpacingUnit", "PIXELS")
        if letter_spacing and letter_spacing != 0:
            if ls_unit == "PERCENT":
                ls_em = round(letter_spacing / 100, 4)
                classes.append(f"tracking-[{ls_em}em]")
            else:
                ls_px = round(letter_spacing, 2)
                classes.append(f"tracking-[{ls_px}px]")

        # Text color — include fill-layer opacity
        if node.fills and len(node.fills) > 0:
            fill = node.fills[0]
            if fill.get("type") == "SOLID" and fill.get("visible", True):
                color = fill.get("color", {})
                fill_opacity = fill.get("opacity", 1.0)
                text_class = TailwindConverter._color_to_tailwind(color, "text", fill_opacity)
                if text_class:
                    classes.append(text_class)

        return classes
    
    @staticmethod
    def get_effect_classes(node: FigmaNode) -> List[str]:
        """Convert effects (shadows, opacity) to Tailwind."""
        classes = []

        for effect in node.effects:
            if not effect.get("visible", True):
                continue
            etype = effect.get("type")
            if etype in ("DROP_SHADOW", "INNER_SHADOW"):
                ox = int(effect.get("offset", {}).get("x", 0))
                oy = int(effect.get("offset", {}).get("y", 0))
                blur   = int(effect.get("radius", 0))
                spread = int(effect.get("spread", 0))
                c = effect.get("color", {})
                r = int(c.get("r", 0) * 255)
                g = int(c.get("g", 0) * 255)
                b = int(c.get("b", 0) * 255)
                a = round(c.get("a", 1.0), 2)

                # Tailwind arbitrary shadow: shadow-[Xpx_Ypx_blur_spread_color]
                shadow_val = f"{ox}px_{oy}px_{blur}px"
                if spread:
                    shadow_val += f"_{spread}px"
                if a < 1:
                    shadow_val += f"_rgba({r},{g},{b},{a})"
                else:
                    shadow_val += f"_rgb({r},{g},{b})"

                prefix = "shadow-[inset_" if etype == "INNER_SHADOW" else "shadow-["
                classes.append(f"{prefix}{shadow_val}]")

        # Node-level opacity — use arbitrary value to avoid Tailwind step mismatch
        if node.opacity < 1:
            classes.append(f"opacity-[{round(node.opacity, 2)}]")

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
    def _color_to_tailwind(color: Dict, prefix: str, fill_opacity: float = 1.0) -> Optional[str]:
        """Convert RGBA color to exact hex Tailwind class, with optional opacity modifier.

        fill_opacity: the fill-layer opacity field (0-1) multiplied with color.a to
        produce the final effective alpha. Emits `bg-[#hex]/NN` when alpha < 1.
        """
        r = int(color.get("r", 0) * 255)
        g = int(color.get("g", 0) * 255)
        b = int(color.get("b", 0) * 255)
        a = color.get("a", 1.0) * fill_opacity

        if a <= 0:
            return f"{prefix}-transparent"

        # Determine base class (white/black use named tokens, everything else uses hex)
        if r >= 255 and g >= 255 and b >= 255:
            base = f"{prefix}-white"
        elif r == 0 and g == 0 and b == 0:
            base = f"{prefix}-black"
        else:
            hex_color = f"#{r:02x}{g:02x}{b:02x}"
            base = f"{prefix}-[{hex_color}]"

        # Append Tailwind opacity modifier when not fully opaque
        if a < 0.99:
            opacity_pct = round(a * 100)
            return f"{base}/{opacity_pct}"

        return base


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
    
    # Persistent cross-workflow cache: mcp-automation/image_cache/{file_id}/{node_id}.png
    PERSISTENT_CACHE_ROOT = Path(__file__).parent.parent.parent / "image_cache"

    def __init__(self, figma_token: str):
        self.figma_token = figma_token.strip()  # strip whitespace/newlines from .env
        self.api_base = "https://api.figma.com/v1"
        self.s3_base = "https://figma-alpha-api.s3.us-west-2.amazonaws.com/img"

    async def download_images(self, file_id: str, nodes: List[FigmaNode], output_dir: Path) -> Dict[str, str]:
        """Download all image-fill images and return mapping of node_id -> local_path.

        Pass order (fastest/cheapest first):
          1. Persistent cross-workflow cache  mcp-automation/image_cache/{file_id}/
             Survives across ALL workflows — zero API calls if previously fetched.
          2. Project-local disk cache  public/images/  (within current build dir).
          3. S3 direct download via imageRef hash
             https://figma-alpha-api.s3.us-west-2.amazonaws.com/img/{imageRef}
             Completely bypasses the rate-limited export API.
          4. GET /v1/files/{key}/images — hash→S3 URL, one lightweight API call.
          5. Node-render endpoint /v1/images/ — last resort, heavy & rate-limited.
        """
        image_nodes = [n for n in nodes if self._has_image_fill(n)]
        if not image_nodes:
            return {}

        # ── Diagnostic: classify nodes upfront ───────────────────────────────
        s3_eligible = [
            n for n in image_nodes
            if any(f.get("type") == "IMAGE" and f.get("imageRef") for f in n.fills)
        ]
        render_only = [n for n in image_nodes if n not in s3_eligible]
        logger.info(
            f"Image download plan: {len(image_nodes)} total — "
            f"{len(s3_eligible)} have imageRef (file-images API eligible), "
            f"{len(render_only)} have no imageRef (node-render API required)"
        )

        images_dir = output_dir / "public" / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        persistent_dir = self.PERSISTENT_CACHE_ROOT / file_id
        persistent_dir.mkdir(parents=True, exist_ok=True)

        image_map: Dict[str, str] = {}
        missing_nodes: List[FigmaNode] = []

        # ── Pass 1: persistent cross-workflow cache ───────────────────────────
        for node in image_nodes:
            safe_id = node.id.replace(':', '_').replace('/', '_')
            persistent_path = persistent_dir / f"{safe_id}.png"
            project_path = images_dir / f"{safe_id}.png"

            if persistent_path.exists() and persistent_path.stat().st_size > 0:
                # Copy into project dir if not already there
                if not (project_path.exists() and project_path.stat().st_size > 0):
                    import shutil
                    shutil.copy2(persistent_path, project_path)
                image_map[node.id] = f"/images/{safe_id}.png"
                logger.debug(f"Persistent cache hit: {safe_id}.png")
            else:
                missing_nodes.append(node)

        if len(image_map):
            logger.info(
                f"Persistent cache: {len(image_map)}/{len(image_nodes)} images reused"
            )
        if not missing_nodes:
            logger.info("All images served from persistent cache — no API calls needed")
            return image_map

        # ── Pass 2: project-local disk cache ─────────────────────────────────
        still_after_local: List[FigmaNode] = []
        for node in missing_nodes:
            safe_id = node.id.replace(':', '_').replace('/', '_')
            filepath = images_dir / f"{safe_id}.png"
            if filepath.exists() and filepath.stat().st_size > 0:
                # Backfill persistent cache
                import shutil
                shutil.copy2(filepath, persistent_dir / f"{safe_id}.png")
                image_map[node.id] = f"/images/{safe_id}.png"
                logger.debug(f"Project cache hit: {safe_id}.png")
            else:
                still_after_local.append(node)

        if len(still_after_local) < len(missing_nodes):
            logger.info(
                f"Project cache: {len(missing_nodes) - len(still_after_local)} more hits"
            )
        missing_nodes = still_after_local
        if not missing_nodes:
            return image_map

        logger.info(f"{len(image_map)} cached, {len(missing_nodes)} need downloading")

        # Build imageRef → node mapping for the remaining nodes
        ref_to_nodes: Dict[str, List[FigmaNode]] = {}
        for node in missing_nodes:
            for fill in node.fills:
                if fill.get("type") == "IMAGE":
                    ref = fill.get("imageRef", "")
                    if ref:
                        ref_to_nodes.setdefault(ref, []).append(node)

        # ── Pass 3: S3 direct download via imageRef (no API call) ────────────
        still_missing: List[FigmaNode] = []
        nodes_resolved_by_s3: set = set()

        async with aiohttp.ClientSession() as session:
            for node in missing_nodes:
                safe_id = node.id.replace(':', '_').replace('/', '_')
                filepath = images_dir / f"{safe_id}.png"

                image_ref: Optional[str] = None
                for fill in node.fills:
                    if fill.get("type") == "IMAGE" and fill.get("imageRef"):
                        image_ref = fill["imageRef"]
                        break

                if image_ref:
                    s3_url = f"{self.s3_base}/{image_ref}"
                    ok = await self._try_s3_direct(session, s3_url, filepath)
                    if ok:
                        import shutil
                        shutil.copy2(filepath, persistent_dir / f"{safe_id}.png")
                        image_map[node.id] = f"/images/{safe_id}.png"
                        nodes_resolved_by_s3.add(node.id)
                        logger.info(f"S3 direct: {safe_id}.png (ref={image_ref[:12]}…)")
                        continue

                still_missing.append(node)

        if nodes_resolved_by_s3:
            logger.info(f"S3 direct bypassed API for {len(nodes_resolved_by_s3)} images")

        # ── Pass 4: file-images API (hash → signed S3 URL, one call) ────────────────
        if still_missing:
            pending_refs = {
                fill["imageRef"]
                for n in still_missing
                for fill in n.fills
                if fill.get("type") == "IMAGE" and fill.get("imageRef")
            }
            file_image_urls: Dict[str, str] = {}
            if pending_refs:
                logger.info(
                    f"File-images API: requesting {len(pending_refs)} hashes "
                    f"(samples: {', '.join(list(pending_refs)[:3])}…)"
                )
                file_image_urls = await self._fetch_file_image_urls(file_id)
                matched = sum(1 for r in pending_refs if r in file_image_urls)
                logger.info(
                    f"File-images API: {len(file_image_urls)} total hashes returned, "
                    f"{matched}/{len(pending_refs)} of our refs matched"
                )

            render_needed: List[FigmaNode] = []
            async with aiohttp.ClientSession() as session:
                for node in still_missing:
                    safe_id = node.id.replace(':', '_').replace('/', '_')
                    filepath = images_dir / f"{safe_id}.png"

                    dl_url: Optional[str] = None
                    for fill in node.fills:
                        if fill.get("type") == "IMAGE":
                            ref = fill.get("imageRef", "")
                            if ref and ref in file_image_urls:
                                dl_url = file_image_urls[ref]
                                break

                    if dl_url:
                        await self._download_file(session, dl_url, filepath)
                        if filepath.exists() and filepath.stat().st_size > 0:
                            import shutil
                            shutil.copy2(filepath, persistent_dir / f"{safe_id}.png")
                            image_map[node.id] = f"/images/{safe_id}.png"
                            logger.info(f"Downloaded (file-images API): {safe_id}.png")
                            continue

                    render_needed.append(node)

            still_missing = render_needed

        # ── Pass 5: node-render endpoint — last resort ────────────────────────
        if still_missing:
            logger.info(
                f"{len(still_missing)} images exhausted all cache/S3 strategies"
                " — falling back to rate-limited node-render API"
            )
            # Send 2 nodes per request to stay well under rate limits.
            # Wait 6s between requests (proactive throttle, avoids hitting 429).
            # On 429: exponential backoff 30s → 60s → 120s → 240s.
            CHUNK = 2
            INTER_CHUNK_DELAY = 6  # seconds between successful requests
            render_urls: Dict[str, str] = {}
            chunks = [still_missing[i:i + CHUNK] for i in range(0, len(still_missing), CHUNK)]
            for ci, chunk in enumerate(chunks):
                chunk_ids = [n.id for n in chunk]
                logger.info(
                    f"Node-render chunk {ci + 1}/{len(chunks)}: {chunk_ids}"
                )
                urls = await self._fetch_image_urls(file_id, chunk_ids)
                render_urls.update(urls)
                if ci < len(chunks) - 1:
                    await asyncio.sleep(INTER_CHUNK_DELAY)

            async with aiohttp.ClientSession() as session:
                for node in still_missing:
                    safe_id = node.id.replace(':', '_').replace('/', '_')
                    filepath = images_dir / f"{safe_id}.png"
                    url = render_urls.get(node.id)
                    if not url:
                        logger.debug(f"No render URL for {node.id}")
                        continue
                    await self._download_file(session, url, filepath)
                    if filepath.exists() and filepath.stat().st_size > 0:
                        import shutil
                        shutil.copy2(filepath, persistent_dir / f"{safe_id}.png")
                        image_map[node.id] = f"/images/{safe_id}.png"
                        logger.info(f"Downloaded (node-render): {safe_id}.png")
                    else:
                        logger.warning(f"Render download empty/failed for {node.id}")

        for node in image_nodes:
            if node.id not in image_map:
                logger.warning(f"Image failed: {node.name} (id={node.id}) — will be skipped in output")

        logger.info(f"Image download complete: {len(image_map)}/{len(image_nodes)} images available")
        return image_map

    async def _try_s3_direct(
        self, session: aiohttp.ClientSession, url: str, filepath: Path
    ) -> bool:
        """Attempt to download an image directly from Figma's S3 CDN.

        Figma stores image fills at:
          https://figma-alpha-api.s3.us-west-2.amazonaws.com/img/{imageRef}
        This works for public/community files. Team/private files return 403
        (bucket is not publicly readable) — in that case the file-images API
        (Pass 4) provides signed S3 URLs that do work.
        Returns True if the file was downloaded successfully.
        """
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status == 200:
                    content = await resp.read()
                    if content:
                        with open(filepath, "wb") as f:
                            f.write(content)
                        return filepath.exists() and filepath.stat().st_size > 0
                elif resp.status == 403 or resp.status == 404:
                    # Not on CDN (vector/component node) — skip silently
                    logger.debug(f"S3 direct {resp.status} for {url[:60]}…")
                else:
                    logger.debug(f"S3 direct returned {resp.status} for {url[:60]}…")
        except Exception as e:
            logger.debug(f"S3 direct failed ({url[:60]}…): {e}")
        return False

    async def _fetch_file_image_urls(self, file_id: str) -> Dict[str, str]:
        """GET /v1/files/{key}/images — returns {imageRef_hash: signed_s3_url} for all
        image fills in the file.  One lightweight call, not rate-limited like the
        node-render endpoint.  Returns empty dict on any failure.

        NOTE: The Figma API wraps the hash map under response["meta"]["images"],
        NOT at the top-level response["images"] key.
        """
        token = self.figma_token.strip()
        url = f"{self.api_base}/files/{file_id}/images"
        loop = asyncio.get_event_loop()
        try:
            def _get():
                return requests.get(
                    url,
                    headers={"X-Figma-Token": token},
                    timeout=30,
                )
            resp = await loop.run_in_executor(None, _get)
            if resp.status_code == 200:
                data = resp.json()
                # Response shape: {"error": false, "status": 200, "meta": {"images": {...}}, "i18n": null}
                # Images are under meta.images, NOT top-level images.
                images = (
                    data.get("meta", {}).get("images")
                    or data.get("images")  # fallback if Figma ever changes shape
                    or {}
                )
                logger.info(
                    f"File-images API: {len(images)} hashes returned"
                    + (f" (sample: {next(iter(images))[:16]}…)" if images else " — EMPTY")
                )
                return images
            logger.warning(
                f"File-images endpoint returned {resp.status_code}: {resp.text[:300]}"
            )
        except Exception as e:
            logger.warning(f"File-images fetch failed: {e}")
        return {}
    
    def _has_image_fill(self, node: FigmaNode) -> bool:
        """Check if node has image fill"""
        if not isinstance(node.fills, list):
            return False
        for fill in node.fills:
            if isinstance(fill, dict) and fill.get("type") == "IMAGE":
                return True
        return False
    
    async def _fetch_image_urls(self, file_id: str, node_ids: List[str]) -> Dict[str, str]:
        """Fetch image export URLs via the node-render endpoint /v1/images/.

        LAST RESORT ONLY — heavy, rate-limited (429 common with many nodes).
        Called only after persistent cache, project cache, S3 direct, and
        file-images API have all failed to supply an image.

        Uses synchronous `requests` (same as _fetch_file) to avoid aiohttp
        header-encoding differences. Retries on 429 with escalating backoff;
        tries both X-Figma-Token and Authorization: Bearer on 403.
        """
        if not node_ids:
            return {}

        # Strip token to eliminate any .env whitespace / newline issues
        token = self.figma_token.strip()

        header_variants = [
            {"X-Figma-Token": token},
            {"Authorization": f"Bearer {token}"},
        ]

        # Caller is responsible for chunking; accept any batch size.
        ids_param = ",".join(node_ids)
        url = f"{self.api_base}/images/{file_id}"
        params = {"ids": ids_param, "format": "png", "scale": "2"}

        # Exponential backoff on 429: 30s → 60s → 120s → 240s (4 attempts)
        max_retries = 4
        base_wait = 30
        loop = asyncio.get_event_loop()

        for attempt in range(max_retries):
            for headers in header_variants:
                header_label = "X-Figma-Token" if "X-Figma-Token" in headers else "Authorization: Bearer"
                try:
                    def _do_get():
                        return requests.get(url, headers=headers, params=params, timeout=30)

                    response = await loop.run_in_executor(None, _do_get)

                    if response.status_code == 200:
                        return response.json().get("images", {})

                    if response.status_code == 403:
                        logger.warning(
                            f"Node-render API 403 with {header_label}"
                            f" — body: {response.text[:500]}"
                        )
                        continue  # try next header variant

                    if response.status_code == 429:
                        wait = base_wait * (2 ** attempt)  # 30, 60, 120, 240
                        logger.warning(
                            f"Node-render API rate limit (429) on attempt {attempt + 1}/{max_retries}. "
                            f"Waiting {wait}s before retry…"
                        )
                        await asyncio.sleep(wait)
                        break  # break header loop, retry outer attempt

                    logger.warning(f"Node-render fetch returned {response.status_code}: {response.text[:200]}")
                    return {}

                except Exception as e:
                    logger.warning(f"Node-render attempt {attempt + 1} ({header_label}) failed: {e}")

        logger.error(f"Node-render API exhausted all {max_retries} attempts for {len(node_ids)} nodes")
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
        
    def _infer_top_layout(self, root: FigmaNode) -> bool:
        """Detect sidebar+content pattern and mutate nodes to enable flex generation.

        Two detection strategies:
          A) Simple (2-6 visible children): find one narrow+tall sidebar child and one
             wide+tall content child — matches clean 2-panel designs.
          B) Multi-child (any count): detect sidebar by absolute position (leftmost, narrow,
             tall enough to be a nav panel) and treat all other visible children as the
             "content area" rendered inside a virtual wrapper div.

        Returns True if inference was applied.  Nothing is hardcoded — only relative ratios.
        """
        if root.has_auto_layout:
            return False  # already has explicit layout

        visible = [c for c in root.children if c.visible]
        if len(visible) < 2:
            return False

        total_w = root.width or 1440
        total_h = root.height or 900
        root_x = root.absolute_bounds.get("x", 0) if root.absolute_bounds else 0
        root_y = root.absolute_bounds.get("y", 0) if root.absolute_bounds else 0

        # ── Strategy A: simple 2-child sidebar+single-content ────────────────
        if 2 <= len(visible) <= 6:
            sidebar_node = None
            content_node = None
            for child in visible[:6]:
                w, h = child.width, child.height
                if w > 0 and h > 0 and w < total_w * 0.28 and h > total_h * 0.70:
                    if sidebar_node is None:
                        sidebar_node = child
                elif w > total_w * 0.50 and h > total_h * 0.50:
                    if content_node is None:
                        content_node = child

            if sidebar_node and content_node:
                root.layout_mode = "HORIZONTAL"
                root.primary_axis_align = "MIN"
                root.counter_axis_align = "MIN"
                root.primary_axis_sizing = "FILL"
                root.counter_axis_sizing = "FILL"
                root._infer_hscreen = True

                sidebar_node.layout_mode = "VERTICAL"
                sidebar_node.primary_axis_sizing = "FILL"
                sidebar_node.counter_axis_sizing = "FIXED"
                sidebar_node.layout_sizing_h = "FIXED"
                sidebar_node.layout_sizing_v = "FILL"
                sidebar_node._infer_shrink_0 = True

                content_node.layout_mode = "VERTICAL"
                content_node.primary_axis_sizing = "FILL"
                content_node.counter_axis_sizing = "FILL"
                content_node.layout_sizing_h = "FILL"
                content_node.layout_sizing_v = "FILL"
                content_node._infer_flex_one = True

                logger.info(
                    f"[Layout Inference A] sidebar='{sidebar_node.name}' (w={int(sidebar_node.width)}px)"
                    f" + content='{content_node.name}' → flex h-screen"
                )
                return True

        # ── Strategy B: multi-child — detect sidebar by position ─────────────
        # Sidebar heuristic: leftmost child (rel_x < 5% of canvas), narrower than
        # 32% of canvas, and at least 30% as tall as the canvas (scrollable ok).
        sidebar_node = None
        for child in visible:
            if not child.absolute_bounds:
                continue
            child_rel_x = child.absolute_bounds.get("x", 0) - root_x
            w, h = child.width, child.height
            if (w > 0 and h > 0
                    and child_rel_x < total_w * 0.05   # hugs left edge
                    and w < total_w * 0.32             # narrower than 32%
                    and h > total_h * 0.30):           # tall enough (scrollable sidebar ok)
                sidebar_node = child
                break

        if not sidebar_node:
            return False

        sidebar_w = int(sidebar_node.width)
        content_nodes = [c for c in visible if c.id != sidebar_node.id]

        # Mutate root → horizontal flex
        root.layout_mode = "HORIZONTAL"
        root.primary_axis_align = "MIN"
        root.counter_axis_align = "MIN"
        root._infer_hscreen = True
        # Signal to generate_component: use multi-content wrapper instead of direct children
        root._infer_sidebar_split = True
        root._sidebar_node = sidebar_node
        root._sidebar_width = sidebar_w
        root._content_nodes = content_nodes
        root._content_bounds = {
            "x": root_x + sidebar_w,
            "y": root_y,
            "width": max(1, total_w - sidebar_w),
            "height": total_h,
        }

        # Mutate sidebar node
        sidebar_node.layout_mode = "VERTICAL"
        sidebar_node.primary_axis_sizing = "FILL"
        sidebar_node.counter_axis_sizing = "FIXED"
        sidebar_node.layout_sizing_h = "FIXED"   # keep pixel width from absolute bounds
        sidebar_node.layout_sizing_v = "FILL"    # height fills the flex row (h-full → _infer_shrink_0 upgrades to h-screen)
        sidebar_node._infer_shrink_0 = True

        logger.info(
            f"[Layout Inference B] sidebar='{sidebar_node.name}' (w={sidebar_w}px)"
            f" + {len(content_nodes)} content nodes → flex row h-screen"
        )
        return True

    @staticmethod
    def _rebase_origin(nodes: List['FigmaNode']) -> Tuple[float, float]:
        """Compute the top-left origin of a group of nodes.

        Returns (min_x, min_y) across all nodes that have absoluteBoundingBox data.
        Use this as the virtual parent's origin when rendering children inside a
        sub-region of the canvas, so the topmost/leftmost child lands at (0, 0).

        Caller builds the virtual parent like:
            ox, oy = ReactCodeGenerator._rebase_origin(content_nodes)
            virtual_parent = FigmaNode({
                "absoluteBoundingBox": {"x": ox, "y": oy, "width": ..., "height": ...},
                ...
            })
        Then _generate_jsx(child, ..., parent=virtual_parent) yields
        rel_x = child.abs_x - ox  and  rel_y = child.abs_y - oy.
        """
        xs = [n.absolute_bounds.get("x", 0) for n in nodes if n.absolute_bounds]
        ys = [n.absolute_bounds.get("y", 0) for n in nodes if n.absolute_bounds]
        return (min(xs) if xs else 0.0, min(ys) if ys else 0.0)

    def _infer_grid_layout(self, node: FigmaNode) -> Optional[Tuple[int, int]]:
        """Detect when a container's children form a regular grid.

        Returns (col_count, gap_px) when all of these are true:
          - 3+ visible children
          - All children within 25% of the average width AND height
          - Children span at least 2 distinct x-position clusters

        Returns None if no grid pattern is found.
        """
        children = [c for c in node.children if c.visible and c.width > 10 and c.height > 10]
        if len(children) < 3:
            return None

        widths  = [c.width  for c in children]
        heights = [c.height for c in children]
        avg_w   = sum(widths)  / len(widths)
        avg_h   = sum(heights) / len(heights)

        # Reject if child sizes vary too much (not a uniform grid)
        if any(abs(w - avg_w) > avg_w * 0.25 for w in widths):
            return None
        if any(abs(h - avg_h) > avg_h * 0.25 for h in heights):
            return None

        # Cluster children into columns by their x-offset relative to the container
        parent_x = node.absolute_bounds.get("x", 0)
        raw_xs   = sorted(c.absolute_bounds.get("x", 0) - parent_x for c in children)

        col_positions: List[float] = []
        for x in raw_xs:
            if not col_positions or abs(x - col_positions[-1]) > avg_w * 0.3:
                col_positions.append(x)

        cols = len(col_positions)
        if cols < 2:
            return None

        # Gap = average spacing between column starts minus average child width
        if cols > 1:
            spans = [col_positions[i + 1] - col_positions[i] for i in range(cols - 1)]
            gap   = max(0, int(sum(spans) / len(spans) - avg_w))
        else:
            gap = 0

        logger.info(
            f"[Grid Inference] '{node.name}': {cols} cols, "
            f"gap≈{gap}px, {len(children)} children (avg {int(avg_w)}×{int(avg_h)}px)"
        )
        return (cols, gap)

    def generate_component(self, node: FigmaNode, component_name: str, image_map: Dict[str, str]) -> str:
        """Generate React component from Figma node.

        For tall frames (height > 1200px, no sidebar) treats each direct child as
        an independent 'const SectionN' so the file stays modular and the AI can
        enhance each section separately within token limits (Fix 2 + Fix 3).
        """
        # ── DEBUG: 2-level node-tree dump ─────────────────────────────────────
        logger.info(
            f"[NodeTree] {component_name} ROOT: name='{node.name}' type={node.type} "
            f"size={int(node.width)}x{int(node.height)} layoutMode={node.layout_mode} "
            f"children={len(node.children)}"
        )
        for i, child in enumerate(node.children[:12]):
            logger.info(
                f"[NodeTree]   [{i}] '{child.name}' type={child.type} "
                f"size={int(child.width)}x{int(child.height)} "
                f"layoutMode={child.layout_mode} layoutPositioning={child.raw.get('layoutPositioning','AUTO')} "
                f"visible={child.visible} children={len(child.children)}"
            )
            for j, gc in enumerate(child.children[:4]):
                logger.info(
                    f"[NodeTree]     [{j}] '{gc.name}' type={gc.type} "
                    f"size={int(gc.width)}x{int(gc.height)} "
                    f"layoutMode={gc.layout_mode} layoutPositioning={gc.raw.get('layoutPositioning','AUTO')}"
                )
        # ──────────────────────────────────────────────────────────────────────

        self._infer_top_layout(node)  # detect sidebar+content and switch to flex before JSX gen
        node._is_root_frame = True    # mark so _generate_jsx can collapse blank top gap

        # Generate imports
        imports = ["import React from 'react'"]
        if any(n.id in image_map for n in self._get_all_nodes(node)):
            imports.append("import Image from 'next/image'")
        imports_str = "\n".join(imports)

        # ── Fix 2: section-by-section for tall landing-page frames ───────────
        # Criteria: frame is tall (> 1200px), has no auto-layout (absolute coords),
        # and no sidebar was detected (not a dashboard).
        # Match convert()'s landing-page criterion exactly (height > width * 1.5)
        # so section-split and AI-full-generation always agree on which frames are pages.
        # Also filter section children to only those large enough to be real sections
        # (height > 100px) so decorative nodes don't inflate the section count.
        is_tall_page = (
            node.height > 1200
            and node.height > (node.width or 1) * 1.5
            and not node.has_auto_layout
            and not getattr(node, '_infer_hscreen', False)
        )
        visible_children = [c for c in node.children if c.visible and c.height > 100]

        if is_tall_page and len(visible_children) >= 2:
            section_consts = []
            section_names = []
            for i, child in enumerate(visible_children):
                sec_name = f"Section{i}"
                section_names.append(sec_name)
                # Each child generated with parent=None so no parent-relative absolute coords
                jsx = self._generate_jsx(child, image_map, indent=2, parent=None)
                # Replace h-screen in the section's root opening tag only so the
                # section doesn't claim the full viewport height inside a scroll container.
                first_tag_end = jsx.find('>')
                if first_tag_end != -1:
                    jsx = jsx[:first_tag_end].replace('h-screen', 'min-h-0') + jsx[first_tag_end:]
                section_consts.append(f"const {sec_name} = () => (\n{jsx}\n)")

            renders = "\n      ".join(
                f'<div className="relative w-full overflow-hidden">\n        <{n} />\n      </div>'
                for n in section_names
            )
            sections_str = "\n\n".join(section_consts)

            logger.info(
                f"[Section Split] {component_name}: {len(visible_children)} sections "
                f"from {int(node.height)}px tall frame"
            )
            return f'''{imports_str}

{sections_str}

export default function {component_name}() {{
  return (
    <div className="w-full flex flex-col isolate">
      {renders}
    </div>
  )
}}
'''

        # ── Sidebar-split: root = flex-row, sidebar + virtual content wrapper ─
        # Triggered by Strategy B in _infer_top_layout when root has no auto-layout
        # but has a detectable sidebar by position (e.g. ContentManagement with 7 children).
        if getattr(node, '_infer_sidebar_split', False):
            sidebar_node  = node._sidebar_node
            content_nodes = node._content_nodes
            sidebar_w     = node._sidebar_width

            # Collect root bg color (so the flex wrapper keeps the canvas background)
            root_bg = ""
            for cls in self.tailwind.get_color_classes(node):
                if cls.startswith("bg-"):
                    root_bg = " " + cls
                    break

            # ── Sidebar ───────────────────────────────────────────────────────
            sidebar_jsx = self._generate_jsx(sidebar_node, image_map, indent=3, parent=node)

            # ── Content wrapper ───────────────────────────────────────────────
            # Rebase origin: compute min(x), min(y) from the actual content nodes
            # so the topmost/leftmost child lands at (0, 0) inside the panel.
            # This is more accurate than root_x + sidebar_w, which can be off by
            # a few pixels when Figma's sidebar doesn't perfectly align with the
            # leftmost content child.
            c_origin_x, c_origin_y = self._rebase_origin(content_nodes)
            content_bounds = {
                "x": c_origin_x,
                "y": c_origin_y,
                "width": max(1, node.width - sidebar_w),
                "height": node.height,
            }
            virtual_parent = FigmaNode({
                "id": "__content_wrapper__",
                "name": "__content_wrapper__",
                "type": "FRAME",
                "layoutMode": "NONE",
                "absoluteBoundingBox": content_bounds,
                "children": [],
                "visible": True,
            })

            content_jsxs = []
            for child in content_nodes:
                cjsx = self._generate_jsx(child, image_map, indent=4, parent=virtual_parent)
                if cjsx:
                    content_jsxs.append(cjsx)

            i3 = "   "   # 3-space indent inside content wrapper
            i4 = "    "  # 4-space indent for content children
            content_inner = "\n".join(content_jsxs)
            content_wrapper = (
                f"{i3}<div className=\"flex-1 min-w-0 h-screen overflow-y-auto relative\">\n"
                f"{content_inner}\n"
                f"{i3}</div>"
            )

            logger.info(
                f"[Sidebar Split] {component_name}: sidebar w={sidebar_w}px "
                f"+ {len(content_nodes)} content nodes"
            )

            return f'''{imports_str}

export default function {component_name}() {{
  return (
    <div className="flex flex-row w-screen h-screen overflow-hidden{root_bg}">
{sidebar_jsx}
{content_wrapper}
    </div>
  )
}}
'''

        # ── Standard single-pass generation ───────────────────────────────────
        jsx = self._generate_jsx(node, image_map, indent=2, parent=None)

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
        classes.extend(self.tailwind.get_sizing_classes(node, parent))   # parent-aware sizing
        classes.extend(self.tailwind.get_color_classes(node))
        classes.extend(self.tailwind.get_text_classes(node))
        classes.extend(self.tailwind.get_effect_classes(node))
        classes.extend(self.responsive.get_responsive_classes(node))

        # Figma clipsContent → overflow-hidden (children cropped to this frame's bounds)
        if node.raw.get("clipsContent") and "overflow-hidden" not in classes:
            classes.append("overflow-hidden")

        # ── Grid inference: detect regular grid of uniform children ──────────
        # Must run before absolute-positioning logic so we can suppress it below.
        if (not node.has_auto_layout
                and node.type in ("FRAME", "GROUP", "COMPONENT", "INSTANCE")
                and node.children):
            grid_result = self._infer_grid_layout(node)
            if grid_result:
                grid_cols, grid_gap = grid_result
                # Replace `relative` (added for absolute-positioned children) with grid
                classes = [c for c in classes if c != "relative"]
                classes.append(f"grid grid-cols-{grid_cols}")
                if grid_gap > 0:
                    classes.append(f"gap-[{grid_gap}px]")
                node._infer_grid = True   # children must NOT be absolutely positioned

        # --- Absolute positioning ---
        # Apply when:
        #   A) parent has no auto-layout (layoutMode=NONE) — all children use absolute coords
        #   B) node has layoutPositioning="ABSOLUTE" — explicitly absolute within auto-layout parent
        # Skip for children of a grid container — the grid handles positioning.
        _parent_no_layout = parent is not None and not parent.has_auto_layout and not getattr(parent, '_infer_grid', False)
        _node_explicit_abs = parent is not None and node.layout_positioning == "ABSOLUTE" and not getattr(parent, '_infer_grid', False)
        if ((_parent_no_layout or _node_explicit_abs) and node.absolute_bounds):
            parent_x = parent.absolute_bounds.get("x", 0)
            parent_y = parent.absolute_bounds.get("y", 0)
            node_x = node.absolute_bounds.get("x", 0)
            node_y = node.absolute_bounds.get("y", 0)
            rel_x = int(node_x - parent_x)
            rel_y = int(node_y - parent_y)

            # Collapse blank top gap: when the parent is the root frame, shift all
            # children up by the y-offset of the topmost visible child so the first
            # element starts at top-0 instead of top-[largeOffset]px.
            if getattr(parent, '_is_root_frame', False):
                sibling_ys = [
                    c.absolute_bounds.get("y", 0)
                    for c in parent.children
                    if getattr(c, 'visible', True) and c.absolute_bounds
                ]
                if sibling_ys:
                    top_gap = int(min(sibling_ys) - parent_y)
                    rel_y = max(0, rel_y - top_gap)

            classes.append("absolute")
            classes.append(f"left-[{rel_x}px]" if rel_x != 0 else "left-0")
            classes.append(f"top-[{rel_y}px]" if rel_y != 0 else "top-0")

        # Container nodes with no auto-layout need `relative` so their absolute
        # children are positioned correctly inside them.
        if (node.children and not node.has_auto_layout
                and node.type in ["FRAME", "GROUP", "COMPONENT", "INSTANCE"]):
            classes.append("relative")

        # ── Apply layout-inference overrides (set by _infer_top_layout) ──────
        # These flags are set in-memory and override whatever the standard
        # Tailwind converters produced, without touching any Figma data.
        if getattr(node, '_infer_hscreen', False):
            # Sidebar layout root: full viewport, no scroll (dashboard).
            # w-screen clips any child that bleeds past the viewport edge.
            classes = [c for c in classes if not (c.startswith('h-[') or c == 'h-full')]
            classes = [c for c in classes if not (c.startswith('w-[') or c == 'w-full')]
            classes.extend(['w-screen', 'h-screen', 'overflow-hidden'])

        if getattr(node, '_infer_shrink_0', False):
            # Sidebar: full viewport height, sticks to top, scrolls its own content.
            # flex-shrink-0 keeps it at the fixed Figma width regardless of content.
            # Remove conflicting overflow/height classes before adding our own.
            classes = [c for c in classes if not (c.startswith('h-[') or c == 'h-full')]
            classes = [c for c in classes if c != 'overflow-hidden']  # let overflow-y-auto win
            classes.extend(['h-screen', 'sticky', 'top-0', 'overflow-y-auto', 'flex-shrink-0'])

        if getattr(node, '_infer_flex_one', False):
            # Content panel: own vertical scroll context, fills remaining width after sidebar.
            classes = [c for c in classes if not (c.startswith('w-[') or c == 'w-full')]
            classes = [c for c in classes if not (c.startswith('h-[') or c == 'h-full')]
            classes.extend(['h-screen', 'overflow-y-auto', 'flex-1', 'min-w-0'])

        # Root container sizing + overflow handling (parent is None = outermost div).
        if parent is None:
            # Always strip fixed pixel sizes from the root — they make the page
            # wider than the viewport and break all responsive layouts.
            classes = [c for c in classes if not (c.startswith('w-[') and c.endswith('px]'))]
            classes = [c for c in classes if not (c.startswith('h-[') and c.endswith('px]'))]
            # Also strip any stale w-screen/h-screen left by earlier passes
            # (the _infer_hscreen block below will re-add w-screen if needed).
            classes = [c for c in classes if c not in ('w-screen', 'h-screen')]

            if getattr(node, '_infer_hscreen', False):
                # Dashboard / sidebar layout: full viewport, no scroll.
                classes.extend(['w-screen', 'h-screen', 'overflow-hidden'])
            else:
                # Landing page / dashboard without inferred sidebar: scrollable, full width.
                classes = [c for c in classes if c != 'overflow-hidden']
                if 'w-full' not in classes:
                    classes.append('w-full')
                if 'min-h-screen' not in classes:
                    classes.append('min-h-screen')
                if 'overflow-x-hidden' not in classes:
                    classes.append('overflow-x-hidden')

        # Build className string
        class_str = " ".join(classes)

        # Opening tag
        if element == "img":
            # Next.js Image component — skip entirely if no valid src (empty src crashes build)
            img_src = image_map.get(node.id, "")
            if not img_src:
                return ""
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
    """AI-powered code generation using Claude vision model for pixel-perfect output"""

    CLAUDE_MODEL = "claude-sonnet-4-20250514"

    def __init__(self):
        self.anthropic_client = None
        self.groq_client = None
        self.model = "meta-llama/llama-4-scout-17b-16e-instruct"  # Groq model ID

        # Anthropic Claude (primary — higher quality, larger context)
        try:
            from anthropic import Anthropic
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if api_key:
                self.anthropic_client = Anthropic(api_key=api_key)
                logger.info(f"AI Code Generator: Anthropic {self.CLAUDE_MODEL} enabled (primary)")
        except ImportError:
            logger.warning("AI Code Generator: anthropic package not installed — run: pip install anthropic")

        # Groq (fallback — fast, free)
        try:
            from groq import Groq
            api_key = os.getenv("GROQ_API_KEY")
            if api_key:
                self.groq_client = Groq(api_key=api_key)
                logger.info(
                    "AI Code Generator: Groq vision enabled"
                    + (" (fallback)" if self.anthropic_client else " (primary)")
                )
        except ImportError:
            logger.warning("AI Code Generator: groq package not installed")

    @property
    def available(self):
        return self.anthropic_client is not None or self.groq_client is not None

    def _call_claude(self, messages: List[Dict], max_tokens: int = 8192) -> Optional[str]:
        """Call Claude via Anthropic API, converting OpenAI message format on the fly.

        Handles:
        - system role → top-level `system` param
        - image_url blocks (data: URIs) → Anthropic base64 image source blocks
        Returns raw text or None on error.
        """
        try:
            system = None
            api_messages = []
            for msg in messages:
                if msg["role"] == "system":
                    system = msg["content"] if isinstance(msg["content"], str) else ""
                else:
                    content = msg["content"]
                    if isinstance(content, str):
                        api_messages.append({"role": msg["role"], "content": content})
                    elif isinstance(content, list):
                        anthropic_blocks = []
                        for block in content:
                            btype = block.get("type")
                            if btype == "text":
                                anthropic_blocks.append({"type": "text", "text": block["text"]})
                            elif btype == "image_url":
                                url = block["image_url"]["url"]
                                if url.startswith("data:"):
                                    # data:image/png;base64,<b64>
                                    meta, b64 = url.split(",", 1)
                                    media_type = meta.split(";")[0].split(":")[1]
                                    anthropic_blocks.append({
                                        "type": "image",
                                        "source": {
                                            "type": "base64",
                                            "media_type": media_type,
                                            "data": b64,
                                        },
                                    })
                                else:
                                    anthropic_blocks.append({
                                        "type": "image",
                                        "source": {"type": "url", "url": url},
                                    })
                        api_messages.append({"role": msg["role"], "content": anthropic_blocks})

            kwargs: Dict = dict(
                model=self.CLAUDE_MODEL,
                max_tokens=max_tokens,
                messages=api_messages,
            )
            if system:
                kwargs["system"] = system

            response = self.anthropic_client.messages.create(**kwargs)
            return response.content[0].text
        except Exception as e:
            logger.error(f"Claude API call failed: {e}")
            return None

    @staticmethod
    def _encode_image_for_vision(image_path: str, max_width: int = 1024) -> str:
        """Load an image, shrink to max_width (preserving aspect ratio), return base64 PNG.

        Keeping images at ≤1024px wide avoids unnecessary token spend while
        preserving enough detail for GPT-4o to judge spacing and colours.
        """
        from PIL import Image
        import io as _io

        img = Image.open(image_path).convert("RGB")
        if img.width > max_width:
            ratio = max_width / img.width
            img = img.resize((max_width, int(img.height * ratio)), Image.Resampling.LANCZOS)

        buf = _io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        import base64 as _b64
        return _b64.b64encode(buf.getvalue()).decode("utf-8")

    def generate_component(
        self,
        node: FigmaNode,
        component_name: str,
        image_map: Dict[str, str],
        figma_screenshot_path: str = None,
        layout_type: str = "dashboard",
    ) -> Optional[str]:
        """Generate component code using AI vision model"""
        if not self.anthropic_client and not self.groq_client:
            return None

        try:
            # Build simplified structure for the prompt
            structure = self._simplify_node(node, image_map, depth=0)
            image_refs = [f"  /images/{path.split('/')[-1]}" for _, path in image_map.items()]

            prompt = self._build_prompt(component_name, structure, image_refs, layout_type=layout_type)

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

            # If screenshot available, use vision (resize to 1024px to save tokens)
            if figma_screenshot_path and Path(figma_screenshot_path).exists():
                img_b64 = self._encode_image_for_vision(figma_screenshot_path)
                messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{img_b64}", "detail": "high"},
                        },
                        {"type": "text", "text": prompt},
                    ],
                })
            else:
                messages.append({"role": "user", "content": prompt})

            logger.info(f"AI generating component: {component_name}")
            if self.anthropic_client:
                logger.info(f"  using Anthropic {self.CLAUDE_MODEL}")
                code = self._call_claude(messages)
                if code is None and self.groq_client:
                    logger.warning("Claude failed — falling back to Groq")
                    code = self.groq_client.chat.completions.create(
                        model=self.model, messages=messages, temperature=0.1, max_tokens=8192,
                    ).choices[0].message.content
            else:
                logger.info(f"  using Groq {self.model}")
                code = self.groq_client.chat.completions.create(
                    model=self.model, messages=messages, temperature=0.1, max_tokens=8192,
                ).choices[0].message.content

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

    def _split_into_sections(self, code: str) -> Optional[Tuple[str, List[str], str]]:
        """Split a sectioned component into (imports, [section_codes], export_footer).

        Recognises code produced by ReactCodeGenerator.generate_component when it
        splits a tall frame into 'const Section0 = () => (...)', 'const Section1 ...',
        etc.  Returns None if the code doesn't have that pattern.
        """
        if 'const Section0' not in code:
            return None

        export_match = re.search(r'\nexport default function', code)
        if not export_match:
            return None

        pre_export = code[:export_match.start()]
        export_footer = code[export_match.start():].strip()

        first_sec = pre_export.find('const Section0')
        imports = pre_export[:first_sec].strip()
        sections_block = pre_export[first_sec:]

        bounds = [m.start() for m in re.finditer(r'const Section\d+ = \(\) =>', sections_block)]
        if not bounds:
            return None

        section_codes: List[str] = []
        for i, start in enumerate(bounds):
            end = bounds[i + 1] if i + 1 < len(bounds) else len(sections_block)
            section_codes.append(sections_block[start:end].strip())

        return imports, section_codes, export_footer

    def _enhance_by_sections(
        self,
        split: Tuple[str, List[str], str],
        component_name: str,
        figma_screenshot_path: Optional[str],
        token_colors: Optional[Dict],
    ) -> Optional[str]:
        """Enhance a sectioned component one section at a time to stay within token limits.

        Each 'const SectionN' block is sent to the AI independently.  The screenshot
        is included in every call so the AI can match each section to the correct
        region of the page.
        """
        imports, section_codes, export_footer = split

        # Build token hint once (shared across sections)
        token_hint = ""
        if token_colors:
            flat: List[str] = []
            for key, val in token_colors.items():
                if isinstance(val, dict):
                    for k, v in val.items():
                        flat.append(f"  {key}.{k} → {v}")
                else:
                    flat.append(f"  {key} → {val}")
            token_hint = "\n\nDesign tokens:\n" + "\n".join(flat) + "\n"

        # Load and resize screenshot once (shared across all section calls)
        img_b64: Optional[str] = None
        if figma_screenshot_path and Path(figma_screenshot_path).exists():
            img_b64 = self._encode_image_for_vision(figma_screenshot_path)

        enhanced_sections: List[str] = []

        for i, sec_code in enumerate(section_codes):
            logger.info(
                f"🎨 [AI ENHANCE] {component_name} section {i + 1}/{len(section_codes)} "
                f"({len(sec_code)} chars)"
            )
            prompt = (
                f"You are a pixel-perfect frontend developer. "
                f"Here is the target design [see image above]. "
                f"This is section {i + 1} of {len(section_codes)} of the page. "
                "Fix the code to match the design EXACTLY for this section.\n\n"
                "Rules:\n"
                "- Use arbitrary Tailwind values for exact measurements "
                "(gap-[13px], text-[#2D3748], w-[280px])\n"
                "- Do not change component structure or add/remove elements\n"
                "- Fix: spacing, padding, margins, colors, font sizes, alignment, "
                "border radius, shadows\n"
                "- Return ONLY the corrected const arrow function — same form as input, "
                "no markdown fences, no explanation\n"
                + token_hint
                + f"\nSection code:\n{sec_code}"
            )

            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a pixel-perfect frontend developer. "
                        "Return ONLY the corrected const arrow function — "
                        "no markdown fences, no explanation."
                    ),
                }
            ]
            if img_b64:
                messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{img_b64}", "detail": "high"},
                        },
                        {"type": "text", "text": prompt},
                    ],
                })
            else:
                messages.append({"role": "user", "content": prompt})

            try:
                if self.anthropic_client:
                    enhanced_sec = self._call_claude(messages)
                    if enhanced_sec is None and self.groq_client:
                        logger.warning(f"Claude failed for section {i} — falling back to Groq")
                        enhanced_sec = self.groq_client.chat.completions.create(
                            model=self.model, messages=messages, temperature=0.1, max_tokens=8192,
                        ).choices[0].message.content
                else:
                    enhanced_sec = self.groq_client.chat.completions.create(
                        model=self.model, messages=messages, temperature=0.1, max_tokens=8192,
                    ).choices[0].message.content

                if enhanced_sec and "```" in enhanced_sec:
                    m = re.search(r'```(?:tsx|jsx|typescript|javascript)?\n(.*?)```', enhanced_sec, re.DOTALL)
                    if m:
                        enhanced_sec = m.group(1).strip()

                if not enhanced_sec or f'const Section{i}' not in enhanced_sec:
                    logger.warning(f"Section {i} enhancement invalid — keeping original")
                    enhanced_sections.append(sec_code)
                else:
                    enhanced_sections.append(enhanced_sec.strip())
            except Exception as e:
                logger.warning(f"Section {i} enhance failed: {e} — keeping original")
                enhanced_sections.append(sec_code)

        return (
            imports + "\n\n"
            + "\n\n".join(enhanced_sections)
            + "\n\n"
            + export_footer
            + "\n"
        )

    def enhance_component(
        self,
        deterministic_code: str,
        component_name: str,
        figma_screenshot_path: str = None,
        token_colors: Dict = None,
    ) -> Optional[str]:
        """Enhance programmatically generated TSX using AI vision.

        The deterministic code already has correct structure, exact pixel sizes,
        and exact hex colors.  The AI's only job is to fix visual details it can
        see in the screenshot that the programmatic pass cannot produce:
        gradient backgrounds, complex shadows, missing effects, border subtleties.
        """
        if not self.anthropic_client and not self.groq_client:
            return None

        # Chunk threshold: anything over 10K chars is split and enhanced piece-by-piece.
        # GPT-4o reliably outputs 8K-char chunks; larger inputs return unchanged code
        # or get truncated even at max_tokens=16384.
        _CHUNK_THRESHOLD = 10_000
        _CHUNK_SIZE = 8_000

        if len(deterministic_code) > _CHUNK_THRESHOLD:
            # Strategy 1: landing-page Section0 pattern
            split = self._split_into_sections(deterministic_code)
            if split:
                logger.info(
                    f"[AI ENHANCE] Using section-split: {len(split[1])} sections, "
                    f"avg {len(deterministic_code) // max(len(split[1]), 1)} chars each, "
                    f"total {len(deterministic_code)} chars"
                )
                result = self._enhance_by_sections(split, component_name, figma_screenshot_path, token_colors)
                if result:
                    return result

            # Strategy 2: JSX-child chunk split (dashboards and any other component)
            logger.info(
                f"[AI ENHANCE] Using JSX chunk-split: "
                f"component={component_name}, code_len={len(deterministic_code)} chars"
            )
            result = self._enhance_by_generic_chunks(
                deterministic_code, component_name, figma_screenshot_path,
                token_colors, chunk_size=_CHUNK_SIZE,
            )
            if result:
                return result

            # Both split strategies failed. For large components skip single-pass:
            # GPT-4o cannot meaningfully process 15K+ chars in one shot — it either
            # echoes unchanged code or hallucinates random style changes.
            _SINGLE_PASS_MAX = 15_000
            if len(deterministic_code) > _SINGLE_PASS_MAX:
                logger.info(
                    f"[AI ENHANCE] Skipping single-pass fallback: component too large "
                    f"({len(deterministic_code)} chars > {_SINGLE_PASS_MAX}). "
                    f"Keeping deterministic output."
                )
                return None
        else:
            logger.info(
                f"[AI ENHANCE] Using single-pass: "
                f"component={component_name}, code_len={len(deterministic_code)} chars"
            )

        # ── Diagnostic: show what we're working with ─────────────────────────
        _screenshot_status = "MISSING (no path)" if not figma_screenshot_path else (
            f"EXISTS ({figma_screenshot_path})" if Path(figma_screenshot_path).exists()
            else f"NOT FOUND ({figma_screenshot_path})"
        )
        _model_label = self.CLAUDE_MODEL if self.anthropic_client else (self.model if self.groq_client else "NONE")
        logger.info(
            f"[AI ENHANCE] INPUT: component={component_name}, "
            f"code_len={len(deterministic_code)}, "
            f"screenshot={_screenshot_status}, "
            f"model={_model_label}"
        )
        logger.info(f"[AI ENHANCE] CODE PREVIEW: {deterministic_code[:200]!r}")

        try:
            # Build optional token colour hint
            token_hint = ""
            if token_colors:
                flat: List[str] = []
                for key, val in token_colors.items():
                    if isinstance(val, dict):
                        for k, v in val.items():
                            flat.append(f"  {key}.{k} → {v}")
                    else:
                        flat.append(f"  {key} → {val}")
                token_hint = (
                    "\n\nDesign tokens (use these Tailwind names for new colour classes):\n"
                    + "\n".join(flat) + "\n"
                )

            enhance_prompt = (
                "You are a pixel-perfect frontend developer. "
                "Here is the target design [see image above]. "
                "Here is the current React + Tailwind code that attempts to reproduce it. "
                "Fix the code to match the design EXACTLY.\n\n"
                "Rules:\n"
                "- Use arbitrary Tailwind values for exact measurements "
                "(gap-[13px], text-[#2D3748], w-[280px])\n"
                "- Do not change component structure or add/remove elements\n"
                "- Fix: spacing, padding, margins, colors, font sizes, alignment, "
                "border radius, shadows\n"
                "- Return ONLY the complete fixed code, no explanation\n"
                + token_hint
                + f"\nCurrent code:\n{deterministic_code}"
            )

            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a pixel-perfect frontend developer. "
                        "Output ONLY raw TSX — no markdown fences, no explanation."
                    ),
                }
            ]

            if figma_screenshot_path and Path(figma_screenshot_path).exists():
                img_b64 = self._encode_image_for_vision(figma_screenshot_path)
                messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{img_b64}", "detail": "high"},
                        },
                        {"type": "text", "text": enhance_prompt},
                    ],
                })
            else:
                messages.append({"role": "user", "content": enhance_prompt})

            logger.info(f"🎨 [AI ENHANCE] Enhancing {component_name} visual details")
            if self.anthropic_client:
                logger.info(f"  using Anthropic {self.CLAUDE_MODEL}")
                enhanced = self._call_claude(messages)
                if enhanced is None and self.groq_client:
                    logger.warning("Claude failed — falling back to Groq")
                    enhanced = self.groq_client.chat.completions.create(
                        model=self.model, messages=messages, temperature=0.1, max_tokens=8192,
                    ).choices[0].message.content
                if enhanced is None:
                    return None
            else:
                logger.info(f"  using Groq {self.model}")
                enhanced = self.groq_client.chat.completions.create(
                    model=self.model, messages=messages, temperature=0.1, max_tokens=8192,
                ).choices[0].message.content

            logger.info(
                f"[AI ENHANCE] RAW RESPONSE: len={len(enhanced)}, "
                f"preview={enhanced[:200]!r}"
            )

            # Strip markdown fences if present
            if "```" in enhanced:
                match = re.search(r'```(?:tsx|jsx|typescript|javascript)?\n(.*?)```', enhanced, re.DOTALL)
                if match:
                    enhanced = match.group(1).strip()

            # Sanity-check 1: must still have export default
            if "export default" not in enhanced:
                logger.warning(
                    f"[AI ENHANCE] REJECTED: no 'export default'. "
                    f"Last 200: {enhanced[-200:]!r}"
                )
                return None

            # Sanity-check 2: truncation guard — output must end with a closing brace.
            # If max_tokens was hit mid-output the file ends with open tags/braces,
            # which causes "Unexpected token" errors at build time.
            _last_char = enhanced.rstrip()[-1] if enhanced.rstrip() else ""
            if _last_char != '}':
                logger.warning(
                    f"[AI ENHANCE] REJECTED: truncated (last char={_last_char!r}). "
                    f"Last 200: {enhanced[-200:]!r}"
                )
                return None

            # NOTE: brace-balance check removed — TSX legitimately has unequal { } counts
            # inside string literals, template expressions, and JSX attributes.
            # The truncation guard above is sufficient to catch incomplete output.

            logger.info(f"✅ [AI ENHANCE] {component_name} enhanced ({len(enhanced)} chars)")
            logger.info(f"[AI ENHANCE] OUTPUT PREVIEW: {enhanced[:200]!r}")
            return enhanced

        except Exception as e:
            logger.error(f"AI enhance failed: {e}")
            return None

    @staticmethod
    def _extract_jsx_body(code: str) -> Optional[Tuple[str, str, str]]:
        """Extract (prefix, jsx_body, suffix) from a TSX component.

        prefix   = everything up to and including 'return ('
        jsx_body = the inner JSX content between the outer return parens
        suffix   = the closing ');\\n}' and any trailing content

        Returns None if the structure can't be reliably identified.
        """
        # Find the LAST 'return (' — it belongs to the export default function
        matches = list(re.finditer(r'\breturn\s*\(', code))
        if not matches:
            return None
        m = matches[-1]
        prefix = code[:m.end()]
        rest = code[m.end():]

        # Walk rest char-by-char tracking paren depth
        depth = 1
        i = 0
        in_str: Optional[str] = None  # current string delimiter (' " `)
        while i < len(rest) and depth > 0:
            ch = rest[i]
            if in_str:
                if ch == "\\" and in_str != "`":
                    i += 2  # skip escaped char
                    continue
                if ch == in_str:
                    in_str = None
            else:
                if ch in ('"', "'", "`"):
                    in_str = ch
                elif ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
            i += 1

        if depth != 0:
            return None  # unbalanced — bail

        jsx_body = rest[:i - 1]   # everything between the outer parens
        suffix   = rest[i - 1:]   # starts with ')'
        return prefix, jsx_body, suffix

    @staticmethod
    def _split_jsx_fragments(jsx_body: str, chunk_size: int = 8_000) -> List[str]:
        """Split a JSX body string into fragments ≤ chunk_size chars.

        Emits a fragment whenever accumulated size ≥ chunk_size AND the current
        line is a safe JSX close boundary (starts with '</' or is a bare closing
        punctuation).  Guarantees at least one fragment.
        """
        lines = jsx_body.splitlines(keepends=True)
        fragments: List[str] = []
        current: List[str] = []
        current_size = 0

        def _is_close(line: str) -> bool:
            s = line.strip()
            return (
                s.startswith("</")
                or s in (")", "};", "})", ");", "}", "/>", "")
                or s.startswith(");")
            )

        for line in lines:
            current.append(line)
            current_size += len(line)
            if current_size >= chunk_size and _is_close(line):
                fragments.append("".join(current))
                current = []
                current_size = 0

        if current:
            fragments.append("".join(current))

        # Merge tiny tail into previous
        if len(fragments) > 1 and len(fragments[-1]) < 300:
            fragments[-2] += fragments[-1]
            fragments.pop()

        return fragments if fragments else [jsx_body]

    @staticmethod
    def _validate_assembled_tsx(code: str, component_name: str) -> bool:
        """Post-assembly sanity check before accepting enhanced code.

        Checks:
          1. Exactly one 'export default'
          2. Last non-whitespace character is '}'
          3. JSX tag balance (open ≈ close, diff ≤ 3)
        """
        if code.count("export default") != 1:
            logger.warning(
                f"[VALIDATE] {component_name}: expected 1 'export default', "
                f"got {code.count('export default')}"
            )
            return False

        last = code.rstrip()[-1] if code.rstrip() else ""
        if last != "}":
            logger.warning(f"[VALIDATE] {component_name}: last char={last!r}, expected '}}'")
            return False

        # JSX tag balance check — strip string literals to avoid false counts
        stripped = re.sub(r'"[^"]*"|\'[^\']*\'|`[^`]*`', '""', code)
        # All opening-like tags: <Tag or <Tag ... >
        all_open   = len(re.findall(r'<[A-Za-z][A-Za-z0-9.]*(?:\s[^>]*)?>', stripped))
        # Self-closing tags: <Tag /> or <Tag .../>  (these match all_open but have no close tag)
        self_close = len(re.findall(r'<[A-Za-z][A-Za-z0-9.]*(?:\s[^>]*)?/>', stripped))
        open_tags  = all_open - self_close  # real opening tags that need a closing tag
        close_tags = len(re.findall(r'</[A-Za-z]', stripped))
        diff = abs(open_tags - close_tags)
        total_tags = open_tags + close_tags + self_close
        threshold  = max(5, int(total_tags * 0.03))
        logger.info(
            f"[VALIDATE] {component_name}: open={open_tags} "
            f"(self-closing={self_close}), close={close_tags}, "
            f"adjusted_diff={diff}, threshold={threshold}"
        )
        if diff > threshold:
            logger.warning(
                f"[VALIDATE] {component_name}: JSX tag imbalance "
                f"(open={open_tags}, close={close_tags}, diff={diff} > threshold={threshold})"
            )
            return False

        return True

    # Keep for use by self_healer.py (imported there)
    @staticmethod
    def _split_code_into_chunks(code: str, chunk_size: int = 8_000) -> List[str]:
        """Legacy splitter — splits raw code at close-tag boundaries.
        Only used internally as fallback; prefer _extract_jsx_body + _split_jsx_fragments.
        """
        lines = code.splitlines(keepends=True)
        chunks: List[str] = []
        current: List[str] = []
        current_size = 0

        def _is_close_boundary(line: str) -> bool:
            s = line.strip()
            return (
                s.startswith("</")
                or s in (")", "};", "})", ");", "}", "/>")
                or s.startswith(");")
            )

        for line in lines:
            current.append(line)
            current_size += len(line)
            if current_size >= chunk_size and _is_close_boundary(line):
                chunks.append("".join(current))
                current = []
                current_size = 0

        if current:
            chunks.append("".join(current))

        if len(chunks) > 1 and len(chunks[-1]) < 500:
            chunks[-2] += chunks[-1]
            chunks.pop()

        return chunks if chunks else [code]

    def _enhance_by_generic_chunks(
        self,
        code: str,
        component_name: str,
        figma_screenshot_path: Optional[str],
        token_colors: Optional[Dict],
        chunk_size: int = 8_000,
    ) -> Optional[str]:
        """Enhance an oversized component by:
        1. Extracting the inner JSX body from 'return (...)'
        2. Splitting the body into JSX fragments ≤ chunk_size chars
        3. Sending each fragment to GPT-4o with a clear 'fragment, not component' prompt
        4. Reassembling prefix + enhanced fragments + suffix
        5. Validating the assembled result before returning

        This avoids the bug where GPT-4o wraps each chunk in its own component,
        producing multiple orphaned export-default functions when concatenated.
        """
        extracted = self._extract_jsx_body(code)
        if extracted is None:
            logger.warning(
                f"[AI ENHANCE] Cannot extract JSX body for {component_name} — skipping chunk enhancement"
            )
            return None

        prefix, jsx_body, suffix = extracted

        # Diagnostic: log the exact prefix so we can see what 'return (' looks like
        logger.info(
            f"[AI ENHANCE] Prefix tail (last 120 chars): {prefix[-120:]!r}"
        )

        fragments = self._split_jsx_fragments(jsx_body, chunk_size)

        logger.info(
            f"[AI ENHANCE] Fragment-split: {len(fragments)} fragments, "
            f"sizes={[len(f) for f in fragments]}"
        )

        # Load screenshot once
        img_b64: Optional[str] = None
        if figma_screenshot_path and Path(figma_screenshot_path).exists():
            img_b64 = self._encode_image_for_vision(figma_screenshot_path)

        token_hint = ""
        if token_colors:
            flat: List[str] = []
            for key, val in token_colors.items():
                if isinstance(val, dict):
                    for k, v in val.items():
                        flat.append(f"  {key}.{k} → {v}")
                else:
                    flat.append(f"  {key} → {val}")
            token_hint = "\n\nDesign tokens:\n" + "\n".join(flat) + "\n"

        enhanced_fragments: List[str] = []
        for i, frag in enumerate(fragments):
            logger.info(f"[AI ENHANCE] Fragment {i + 1}/{len(fragments)} ({len(frag)} chars)")

            prompt = (
                "You are a pixel-perfect frontend developer.\n"
                + ("The target design is in the image above.\n" if img_b64 else "")
                + f"This is JSX fragment {i + 1} of {len(fragments)} from component '{component_name}'.\n\n"
                "CRITICAL: This is a RAW JSX FRAGMENT — NOT a complete React component.\n"
                "DO NOT add 'export default', 'function', 'const', 'return', or any wrapper.\n\n"
                "STRICT RULES:\n"
                "1. PRESERVE all colors, backgrounds, and values that already match the design. "
                "If a style value is not visibly wrong, DO NOT change it. When in doubt, keep the original.\n"
                "2. Do NOT add or remove JSX elements — keep the exact same element tree.\n"
                "3. Do NOT restructure or rewrite JSX — only change className strings.\n"
                "4. Use arbitrary Tailwind values for fixes: gap-[13px], w-[280px], text-[#2D3748].\n"
                "5. Return ONLY the corrected JSX fragment — no markdown fences, no explanation.\n"
                + token_hint
                + f"\nJSX fragment to improve:\n{frag}"
            )

            messages = [
                {
                    "role": "system",
                    "content": (
                        "You output ONLY raw JSX fragments. "
                        "Never wrap output in a function, export, or component declaration. "
                        "No markdown fences, no explanation."
                    ),
                }
            ]
            if img_b64:
                messages.append({
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}", "detail": "high"}},
                        {"type": "text", "text": prompt},
                    ],
                })
            else:
                messages.append({"role": "user", "content": prompt})

            try:
                if self.anthropic_client:
                    enhanced_frag = self._call_claude(messages)
                    if enhanced_frag is None and self.groq_client:
                        enhanced_frag = self.groq_client.chat.completions.create(
                            model=self.model, messages=messages, temperature=0.1, max_tokens=8192,
                        ).choices[0].message.content
                else:
                    enhanced_frag = self.groq_client.chat.completions.create(
                        model=self.model, messages=messages, temperature=0.1, max_tokens=8192,
                    ).choices[0].message.content

                if enhanced_frag and "```" in enhanced_frag:
                    m = re.search(r'```(?:tsx|jsx|typescript|javascript|html)?\n(.*?)```', enhanced_frag, re.DOTALL)
                    if m:
                        enhanced_frag = m.group(1)

                # Reject if GPT-4o wrapped output in a component anyway
                if enhanced_frag and "export default" in enhanced_frag:
                    logger.warning(
                        f"[AI ENHANCE] Fragment {i + 1}: AI wrapped output in component — "
                        "keeping original fragment"
                    )
                    enhanced_fragments.append(frag)
                elif not enhanced_frag or not enhanced_frag.strip():
                    logger.warning(f"[AI ENHANCE] Fragment {i + 1}: empty response — keeping original")
                    enhanced_fragments.append(frag)
                else:
                    enhanced_fragments.append(enhanced_frag)

            except Exception as e:
                logger.warning(f"[AI ENHANCE] Fragment {i + 1} failed: {e} — keeping original")
                enhanced_fragments.append(frag)

        # Reassemble: prefix + enhanced body + suffix
        enhanced_body = "".join(enhanced_fragments)
        result = prefix + enhanced_body + suffix

        # ── Post-processing ────────────────────────────────────────────────────
        # 1. Fix whitespace: ensure 'return (' is followed by a newline, not spaces.
        result = re.sub(r'(return\s*\()[ \t]+(<)', r'\1\n    \2', result)

        # 2. Restore root className + hex colors from the original.
        result = self._restore_root_classname(code, result, component_name)

        # Diagnostic: log first 20 lines so we can see actual output
        first_20 = "\n".join(result.splitlines()[:20])
        logger.info(f"[AI ENHANCE] First 20 lines of assembled result:\n{first_20}")

        # 3. Tag-balance sanity check
        if not self._validate_assembled_tsx(result, component_name):
            logger.warning(f"[AI ENHANCE] Tag validation failed — keeping deterministic output")
            return None

        # 4. SWC syntax check — compile the assembled TSX in a temp file.
        #    If it fails, fall back to deterministic code (always compiles).
        syntax_ok = self._check_tsx_syntax(result, component_name)
        if not syntax_ok:
            logger.warning(
                f"[AI ENHANCE] SWC syntax check failed — keeping deterministic output "
                f"(component={component_name})"
            )
            return None

        logger.info(f"[AI ENHANCE] Fragment reassembly OK: {len(result)} chars")
        return result

    @staticmethod
    def _restore_root_classname(original: str, enhanced: str, component_name: str) -> str:
        """Restore the root div's className from the original deterministic code.

        The root className carries layout (w-screen h-screen flex-row) and
        background colors that GPT-4o commonly corrupts when it only sees an
        inner fragment.  We always keep the original root classes verbatim.

        Also scans for any hex color utility (`bg-[#...]`, `text-[#...]`, etc.)
        that appears in the enhanced code but NOT in the original and replaces it
        with the most similar original color.  This catches cases where AI
        changes non-root colors without a design justification.
        """
        # ── Step 1: Restore root div className ────────────────────────────────
        root_pat = re.compile(r'(<div\b[^>]*?\bclassName=")([^"]+)(")')
        orig_root = root_pat.search(original)
        if orig_root:
            orig_root_classes = orig_root.group(2)
            _first = [True]

            def _restore_first(m):
                if _first[0]:
                    _first[0] = False
                    if m.group(2) != orig_root_classes:
                        logger.info(
                            f"[COLOR RESTORE] {component_name}: root className restored "
                            f"({m.group(2)[:60]!r} → {orig_root_classes[:60]!r})"
                        )
                    return f"{m.group(1)}{orig_root_classes}{m.group(3)}"
                return m.group(0)

            enhanced = root_pat.sub(_restore_first, enhanced)

        # ── Step 2: Restore any hex color utility not present in original ─────
        color_util_pat = re.compile(
            r'\b(bg|text|border|from|to|via|ring|shadow|outline|fill|stroke)'
            r'-\[(#[0-9a-fA-F]{3,8}|rgba?\([^)]+\))\]'
        )
        orig_colors  = set(color_util_pat.findall(original))   # {(prefix, value), ...}
        orig_hex_set = {v for _, v in orig_colors}             # set of original hex values

        def _restore_color(m: re.Match) -> str:
            prefix_cls, color_val = m.group(1), m.group(2)
            if (prefix_cls, color_val) in orig_colors:
                return m.group(0)  # present in original — keep
            if color_val in orig_hex_set:
                return m.group(0)  # same hex used in original (different util) — keep
            # Totally new color: revert to the first original color with same prefix
            fallback_colors = [v for p, v in orig_colors if p == prefix_cls]
            if fallback_colors:
                repl = f"{prefix_cls}-[{fallback_colors[0]}]"
                logger.info(
                    f"[COLOR RESTORE] {component_name}: {m.group(0)!r} → {repl!r} "
                    "(not in original, reverting)"
                )
                return repl
            return m.group(0)

        enhanced = color_util_pat.sub(_restore_color, enhanced)
        return enhanced

    @staticmethod
    def _check_tsx_syntax(code: str, component_name: str) -> bool:
        """Verify TSX syntax using bracket/tag balance check.

        SWC is not required — the bracket balance check catches the most
        common failure modes (unbalanced parens, fragment boundary breaks).
        """
        return AICodeGenerator._bracket_balance_check(code, component_name)

    @staticmethod
    def _bracket_balance_check(code: str, component_name: str) -> bool:
        """Lightweight fallback: verify paren and angle-bracket balance.

        Not a full parser, but catches the most common fragment-boundary errors
        (unclosed tags, runaway JSX expressions) that SWC would reject.
        """
        # Paren balance (covers 'return ( ... )' wrapping)
        paren_depth = 0
        in_str: Optional[str] = None
        for ch in code:
            if in_str:
                if ch == in_str:
                    in_str = None
            else:
                if ch in ('"', "'", '`'):
                    in_str = ch
                elif ch == '(':
                    paren_depth += 1
                elif ch == ')':
                    paren_depth -= 1

        if paren_depth != 0:
            logger.warning(
                f"[BRACKET CHECK] {component_name}: paren imbalance "
                f"(depth={paren_depth} at end)"
            )
            return False

        # Angle-bracket balance (very rough — only catches gross mismatches)
        stripped = re.sub(r'"[^"]*"|\'[^\']*\'|`[^`]*`', '""', code)
        opens  = len(re.findall(r'<[A-Za-z]', stripped))
        closes = len(re.findall(r'(?:</[A-Za-z]|/>)', stripped))
        if abs(opens - closes) > max(5, opens * 0.05):
            logger.warning(
                f"[BRACKET CHECK] {component_name}: angle-bracket imbalance "
                f"(opens={opens}, closes={closes})"
            )
            return False

        logger.info(f"[BRACKET CHECK] {component_name}: OK (paren=0, opens={opens}, closes={closes})")
        return True

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

        # Children (limit depth to 12 levels to capture nested sidebars, cards, grids)
        if depth < 12 and node.children:
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

    def _build_prompt(
        self,
        component_name: str,
        structure: Dict,
        image_refs: List[str],
        layout_type: str = "dashboard",
    ) -> str:
        """Build the prompt for AI code generation.

        layout_type: "dashboard"  → sidebar+content layout rules
                     "landing_page" → vertical scrollable page rules
        """
        images_list = "\n".join(image_refs) if image_refs else "  (none)"

        # Truncate structure to avoid token limits
        structure_str = json.dumps(structure, indent=1)
        if len(structure_str) > 32000:
            structure_str = structure_str[:32000] + "\n... (truncated - rely on the screenshot for remaining details)"

        # Detect layout and build mandatory skeleton if sidebar found (dashboard only)
        layout_hint, layout_info = self._analyze_layout(structure)

        if layout_type == "dashboard" and layout_info and layout_info.get("type") == "sidebar+content":
            skeleton_section = self._build_layout_skeleton(layout_info, component_name) + "\n\n"
        else:
            skeleton_section = ""

        if layout_type == "landing_page":
            render_rules = """━━━ RENDER EVERY SECTION IN FULL ━━━

LANDING PAGE RULES:
- The root element must be a <div> with w-full (NOT h-screen, NOT overflow-hidden — the page must scroll).
- Reproduce EVERY section visible in the screenshot top-to-bottom: hero, features, testimonials, pricing, FAQ, footer, etc.
- Each section is a full-width block. Use flex, grid, or plain block layout as visible in the screenshot.
- Hero section: exact background color/gradient, heading, subheading, CTA buttons, illustration or image.
- Image sections: use <Image src="..." width={N} height={N} alt="..."> with exact pixel dimensions from structure.
- Text content: copy ALL visible text exactly as shown — headings, paragraphs, labels, links.
- Buttons/CTAs: exact background, text, border-radius, padding from structure data.
- Use grid for any multi-column layouts (cards, feature lists, pricing tiers). Count columns from screenshot.
- Footer: full background color, all links, copyright text.

SCROLL RULES:
- NEVER add overflow-hidden to the root or any section container.
- Sections stack vertically — let the browser scroll naturally."""
        else:
            render_rules = """━━━ RENDER EVERY SECTION IN FULL ━━━

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
- ALL tabs with label + count badge; active tab uses exact highlight color from structure."""

        return f"""You are a pixel-perfect Figma-to-React converter. Reproduce EVERY element in the screenshot as a single React + Tailwind CSS component.

Component name: {component_name}

Available images (use these exact paths — never invent paths):
{images_list}

{layout_hint}{skeleton_section}Figma structure data (exact colors, sizes, spacing — use these values):
{structure_str}

{render_rules}

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
        self.token_extractor = DesignTokenExtractor()
        self.classifier = ComponentClassifier()
        self.prop_generator = PropBasedGenerator()
        self.code_generator = ReactCodeGenerator()
        self.ai_generator = AICodeGenerator()
        self.image_downloader = ImageDownloader(figma_token)

        # MCP client for exact Figma Variables (design tokens with real names).
        # Degrades gracefully if npx / figma-developer-mcp is unavailable.
        try:
            from tools.figma_mcp_client import FigmaMCPClient
            self.mcp_client: Optional[FigmaMCPClient] = FigmaMCPClient(figma_token)
            logger.info("✅ Figma MCP client ready")
        except Exception as _e:
            logger.warning(f"MCP client unavailable — design tokens from AST only: {_e}")
            self.mcp_client = None
    
    async def _export_frame_image(self, file_id: str, node_id: str, output_dir: Path) -> Optional[str]:
        """Get a PNG screenshot of a Figma frame using a 4-source fallback chain.

        Sources tried in order (fastest/cheapest first):
          a) Persistent cross-run cache  → instant, zero API calls
          b) Figma images/render API     → highest quality, subject to 429
          c) Playwright embed screenshot → no API, works for shared files
          d) Returns None               → caller falls back to file thumbnail

        Successful results from b/c are stored in the persistent cache so
        subsequent runs skip all API calls.
        """
        import shutil as _shutil
        safe_id = node_id.replace("-", "_").replace(":", "_").replace(";", "_")

        # Shared paths
        persistent_cache_dir = ImageDownloader.PERSISTENT_CACHE_ROOT / file_id
        persistent_cache_dir.mkdir(parents=True, exist_ok=True)
        persistent_path = persistent_cache_dir / f"frame_{safe_id}.png"
        local_path = output_dir / f"_frame_{safe_id}.png"

        def _save_and_cache(data: bytes) -> str:
            """Write to both local and persistent cache, return local path string."""
            local_path.write_bytes(data)
            try:
                persistent_path.write_bytes(data)
            except Exception:
                pass
            return str(local_path)

        # ── a) Persistent cache ───────────────────────────────────────────────
        if persistent_path.exists():
            _cached_size = persistent_path.stat().st_size
            if _cached_size < 100_000:
                logger.warning(f"[FRAME] a) Cached screenshot too small ({_cached_size // 1024}KB) — likely a thumbnail, deleting and re-downloading")
                persistent_path.unlink()
            else:
                logger.info(f"[FRAME] a) Persistent cache hit: {persistent_path.name} ({_cached_size // 1024}KB)")
                _shutil.copy2(str(persistent_path), str(local_path))
                return str(local_path)

        if local_path.exists() and local_path.stat().st_size >= 100_000:
            logger.info(f"[FRAME] a) Project cache hit: {local_path.name} ({local_path.stat().st_size // 1024}KB)")
            return str(local_path)

        # ── b) Figma images/render API ────────────────────────────────────────
        logger.info(f"[FRAME] b) Trying Figma render API for node {node_id}…")
        try:
            await asyncio.sleep(5)  # avoid hitting same bucket as node-image downloads

            headers = {"X-Figma-Token": self.figma_token.strip()}
            loop = asyncio.get_event_loop()

            def _render_api_call():
                r = requests.get(
                    f"{self.api_base}/images/{file_id}",
                    headers=headers,
                    params={"ids": node_id, "format": "png", "scale": "2"},
                    timeout=30,
                )
                if r.status_code == 429:
                    logger.warning(f"[FRAME] b) 429 — waiting 30s and retrying")
                    time.sleep(30)
                    r = requests.get(
                        f"{self.api_base}/images/{file_id}",
                        headers=headers,
                        params={"ids": node_id, "format": "png", "scale": "2"},
                        timeout=30,
                    )
                return r

            resp = await loop.run_in_executor(None, _render_api_call)

            if resp.status_code == 200:
                image_url = resp.json().get("images", {}).get(node_id)
                if image_url:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=60)) as r:
                            if r.status == 200:
                                data = await r.read()
                                if len(data) > 10_000:
                                    path = _save_and_cache(data)
                                    logger.info(f"[FRAME] b) Render API success: {len(data) // 1024}KB")
                                    return path
            else:
                logger.warning(f"[FRAME] b) Render API returned {resp.status_code} — trying Playwright")
        except Exception as e:
            logger.warning(f"[FRAME] b) Render API failed: {e} — trying Playwright")

        # ── c) Playwright embed screenshot ────────────────────────────────────
        logger.info(f"[FRAME] c) Trying Playwright embed screenshot…")
        playwright_result = await self._screenshot_figma_via_playwright(
            file_id=file_id,
            node_id=node_id,
            output_path=local_path,
        )
        if playwright_result and local_path.exists() and local_path.stat().st_size > 10_000:
            try:
                persistent_path.write_bytes(local_path.read_bytes())
            except Exception:
                pass
            logger.info(f"[FRAME] c) Playwright success: {local_path.stat().st_size // 1024}KB")
            return str(local_path)

        # ── d) No source available ────────────────────────────────────────────
        logger.warning(f"[FRAME] All screenshot sources failed for node {node_id} — caller will use thumbnail")
        return None

    async def _screenshot_figma_via_playwright(
        self,
        file_id: str,
        node_id: str,
        output_path: Path,
        width: int = 1920,
    ) -> bool:
        """Take a screenshot of a Figma design using Playwright (headless Chromium).

        Uses the public embed URL so no Figma session/cookies are required for
        files with link sharing enabled.  Returns True on success.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning("[FRAME] playwright not installed — run: pip install playwright && playwright install chromium")
            return False

        # Construct embed URL — works for files with "Anyone with the link" sharing
        node_id_enc = node_id.replace(":", "%3A").replace("+", "%2B")
        figma_design_url = f"https://www.figma.com/design/{file_id}?node-id={node_id_enc}"
        from urllib.parse import quote as _quote
        embed_url = f"https://www.figma.com/embed?embed_host=share&url={_quote(figma_design_url, safe='')}"

        logger.info(f"[FRAME] Playwright: opening {embed_url[:80]}…")

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                ctx = await browser.new_context(
                    viewport={"width": width, "height": 1080},
                    device_scale_factor=1,
                )
                page = await ctx.new_page()

                # Navigate; use domcontentloaded (faster) then poll for canvas
                await page.goto(embed_url, wait_until="domcontentloaded", timeout=30_000)

                # Wait for Figma canvas — try several known selectors
                canvas_loaded = False
                for selector in [
                    '[data-testid="canvas-container"]',
                    'canvas',
                    '.figma-embed',
                    '[class*="canvas"]',
                ]:
                    try:
                        await page.wait_for_selector(selector, timeout=12_000)
                        canvas_loaded = True
                        logger.info(f"[FRAME] Playwright: canvas found via '{selector}'")
                        break
                    except Exception:
                        continue

                if not canvas_loaded:
                    # Fallback: just wait for the page to settle
                    logger.info("[FRAME] Playwright: canvas selector not found — waiting 10s")
                    await page.wait_for_timeout(10_000)

                # Extra settle time for Figma to finish rendering layers
                await page.wait_for_timeout(3_000)

                await page.screenshot(path=str(output_path), full_page=False)
                await browser.close()

            if output_path.exists() and output_path.stat().st_size > 10_000:
                return True

            logger.warning("[FRAME] Playwright: screenshot file too small — likely a login/error page")
            return False

        except Exception as e:
            logger.warning(f"[FRAME] Playwright screenshot failed: {e}")
            return False

    async def convert(self, figma_url: str, output_dir: Path, figma_screenshot_path: str = None) -> Dict:
        """Convert Figma to production-ready code"""
        try:
            file_id, target_node_id = self._extract_file_id(figma_url)
            self._target_node_id = target_node_id
            logger.info(f"🎨 Converting Figma file: {file_id}" + (f" (node: {target_node_id})" if target_node_id else ""))
            
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

            # Classify every node in the tree into a semantic type
            classified = self.classifier.classify_tree(root)
            type_counts: Dict[str, int] = {}
            for sem in classified.values():
                type_counts[sem] = type_counts.get(sem, 0) + 1
            logger.info(
                f"✅ Component classification: "
                + ", ".join(f"{t}×{n}" for t, n in sorted(type_counts.items()))
                + f" ({len(classified)} total)"
            )

            # Extract design tokens and write src/tokens.ts before generating components
            self.token_extractor = DesignTokenExtractor()  # reset between runs
            self.token_extractor.extract(root)
            self.token_extractor.write_tokens_file(output_dir)
            logger.info("✅ Design tokens extracted → src/tokens.ts")

            # ── MCP: fetch Figma Variables for exact design token names ───────────
            # Uses figma-developer-mcp via stdio. Falls back silently if unavailable.
            mcp_colors: Dict[str, str] = {}
            if self.mcp_client:
                try:
                    mcp_vars = await self.mcp_client.get_local_variables(file_id)
                    for var_name, hex_val in mcp_vars.get("colors", {}).items():
                        # Normalise path-based names: "Colors/Primary/500" → "primary-500"
                        parts = var_name.lower().split("/")
                        if parts and parts[0] in ("colors", "color"):
                            parts = parts[1:]
                        key = "-".join(p.strip() for p in parts if p.strip())
                        if key:
                            mcp_colors[key] = hex_val
                    if mcp_colors:
                        logger.info(f"✅ MCP Variables: {len(mcp_colors)} exact color tokens")
                    else:
                        logger.info("ℹ️ MCP: file has no Figma Variables — using AST tokens")
                except Exception as _e:
                    logger.warning(f"MCP variable fetch failed ({_e}) — using AST tokens only")

            # Merge: AST-extracted colors as base, Figma Variables override/extend
            _ast_colors: Dict[str, str] = self.token_extractor.build_tokens().get("colors", {})
            _merged_colors: Dict[str, str] = {**_ast_colors, **mcp_colors}

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

            # Generate reusable UI primitives (Button / Card / Badge) from classified nodes
            ui_files = self.prop_generator.generate_ui_components(classified, root, output_dir)
            if ui_files:
                logger.info(f"✅ UI components written: {', '.join(Path(p).name for p in ui_files)}")
            else:
                logger.info("ℹ️ No Button/Card/Badge nodes found — skipping ui/ generation")

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
            use_decompose = os.getenv('DECOMPOSE', 'false').lower() == 'true'
            if use_decompose:
                logger.info("🧩 Decomposed pipeline enabled (DECOMPOSE=true)")

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

                # ——— Decomposed pipeline (DECOMPOSE=true): generate each semantic
                # component independently then compose a page layout. Falls back to
                # the monolithic path if decomposition produces no specs.
                if use_decompose and use_ai and self.ai_generator.available:
                    logger.info(f"🧩 [DECOMPOSE] Breaking {comp_name} into components")
                    _decomp = self._convert_decomposed(
                        frame, comp_name, _ai_screenshot_path,
                        output_dir, image_map, components_dir,
                    )
                    if _decomp:
                        generated.extend(_decomp)
                        continue  # skip monolithic path for this frame
                    logger.warning(f"[DECOMPOSE] Fell back to monolithic pipeline for {comp_name}")

                # Detect layout type BEFORE generating code so we choose the right strategy.
                # A landing page is: taller-than-wide AND no sidebar+content child pattern.
                # A dashboard is: has a narrow sidebar child alongside a wide content child.
                # We use raw frame dimensions for a quick pre-check (no mutation yet).
                frame_h = frame.height
                frame_w = frame.width or 1
                _is_landing_page = (frame_h > frame_w * 1.5)

                # Step 1: generate deterministic code from exact Figma measurements.
                # For landing pages this gives us absolute-positioned fallback code;
                # for dashboards with a sidebar it produces a solid flex skeleton.
                logger.info(f"⚙️ [PROGRAMMATIC] Generating {comp_name} from Figma structure")
                code = self.code_generator.generate_component(frame, comp_name, image_map)
                logger.info(f"✅ [PROGRAMMATIC] {comp_name} done ({len(code)} chars)")

                # After generate_component ran _infer_top_layout, check if a sidebar was found.
                # If _infer_hscreen is set, the static code already has a correct dashboard skeleton.
                _dashboard_detected = getattr(frame, '_infer_hscreen', False)

                # Override landing page flag: if dashboard was detected, trust the static skeleton.
                if _dashboard_detected:
                    _is_landing_page = False

                logger.info(
                    f"[Layout Type] {comp_name}: "
                    f"{'landing page' if _is_landing_page else 'dashboard/other'} "
                    f"(h={int(frame_h)}px w={int(frame_w)}px, dashboard_detected={_dashboard_detected})"
                )

                if use_ai and self.ai_generator.available:
                    if _is_landing_page:
                        # Landing page: use full AI generation with landing-page-specific rules.
                        # The AI sees the screenshot and builds a proper vertical scroll layout.
                        logger.info(f"🎨 [AI FULL] Generating landing page {comp_name} from scratch")
                        ai_code = self.ai_generator.generate_component(
                            frame, comp_name, image_map,
                            figma_screenshot_path=_ai_screenshot_path,
                            layout_type="landing_page",
                        )
                        if ai_code:
                            code = ai_code
                            logger.info(f"✅ [AI FULL] {comp_name} done ({len(code)} chars)")
                        else:
                            logger.warning(f"⚠️ [AI FULL] returned nothing for {comp_name} — keeping programmatic output")
                    else:
                        # Dashboard: enhance visual details only — structure from static code stays intact
                        enhanced = self.ai_generator.enhance_component(
                            code, comp_name, _ai_screenshot_path,
                            token_colors=_merged_colors,
                        )
                        if enhanced:
                            code = enhanced
                        else:
                            logger.warning(f"⚠️ [AI ENHANCE] returned nothing for {comp_name} — keeping programmatic output")
                elif use_ai:
                    logger.warning(f"⚠️ USE_AI=true but GROQ_API_KEY not set — using programmatic output")

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
            self._generate_tailwind_config(output_dir, _merged_colors)
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

            first_frame = frames[0] if frames else None
            return {
                "success": True,
                "components": generated,
                "images": len(image_map),
                "output_dir": str(output_dir),
                "file_name": figma_data.get("name", "Untitled"),
                "first_frame_node_id": first_frame.id if first_frame else None,
                "frame_width": int(first_frame.width) if first_frame else None,
                "frame_height": int(first_frame.height) if first_frame else None,
                "thumbnail_url": figma_data.get("thumbnailUrl"),  # Pre-generated, no extra API call
                "registry_path": str(registry_path),
            }
            
        except Exception as e:
            logger.error(f"❌ Conversion failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }
    
    # ──────────────────────────────────────────────────────────────────────────
    # Decomposed pipeline
    # ──────────────────────────────────────────────────────────────────────────

    def _convert_decomposed(
        self,
        frame,               # FigmaNode
        comp_name: str,
        frame_screenshot_path: Optional[str],
        output_dir: Path,
        image_map: Dict[str, str],
        components_dir: Path,
    ) -> List[Dict]:
        """
        Decompose *frame* into semantic components, generate each independently
        with Claude (cropped screenshot + structured node description), then emit
        a page layout component that imports and composes them.

        Returns a list with one entry — the page layout — so that
        _generate_nextjs_structure writes a clean page.tsx importing one root
        component.  Returns [] on total failure so the caller falls back.
        """
        try:
            from tools.component_decomposer import ComponentDecomposer
        except ImportError:
            try:
                from component_decomposer import ComponentDecomposer
            except ImportError:
                logger.error("[DECOMPOSE] component_decomposer not found — falling back")
                return []

        decomposer = ComponentDecomposer()
        specs = decomposer.decompose(frame)

        if not specs:
            logger.warning(f"[DECOMPOSE] No specs for {comp_name} — falling back")
            return []

        spec_summary = [
            f"{s.name}(×{s.instance_count})" if s.is_template else s.name
            for s in specs
        ]
        logger.info(f"[DECOMPOSE] {comp_name} → {len(specs)} components: [{', '.join(spec_summary)}]")

        # ── Load frame screenshot for cropping ───────────────────────────────
        frame_img = None
        img_w = img_h = 0
        if frame_screenshot_path and Path(frame_screenshot_path).exists():
            try:
                from PIL import Image as _PILImage
                frame_img = _PILImage.open(frame_screenshot_path)
                img_w, img_h = frame_img.size
                logger.info(f"[DECOMPOSE] Frame screenshot loaded: {img_w}×{img_h}")
            except Exception as _e:
                logger.warning(f"[DECOMPOSE] Could not load frame screenshot: {_e}")

        # Scale factor: Figma design px → screenshot px
        scale_x = img_w / max(frame.width, 1) if frame_img else 1.0
        scale_y = img_h / max(frame.height, 1) if frame_img else 1.0

        crops_dir = output_dir / "_crops"
        crops_dir.mkdir(exist_ok=True)

        # ── Sanitize all component names before any file I/O ─────────────────
        # Strip every non-alphanumeric character (commas, dots, spaces, etc.)
        # and ensure the name starts with an uppercase letter.
        for spec in specs:
            spec.name = re.sub(r'[^a-zA-Z0-9]', '', spec.name)
            if spec.name and not spec.name[0].isupper():
                spec.name = spec.name[0].upper() + spec.name[1:]
            if not spec.name:
                spec.name = "Component"

        # ── Generate each component ──────────────────────────────────────────
        generated_specs: List[Dict] = []
        for spec in specs:
            # 1. Crop the frame screenshot to this component's bounding box
            cropped_path: Optional[str] = None
            if frame_img is not None:
                try:
                    x, y, w, h = spec.crop_box
                    sx = int(x * scale_x);  sy = int(y * scale_y)
                    sw = max(1, int(w * scale_x));  sh = max(1, int(h * scale_y))
                    sx = min(sx, img_w - 1);  sy = min(sy, img_h - 1)
                    sw = min(sw, img_w - sx);  sh = min(sh, img_h - sy)
                    if sw > 0 and sh > 0:
                        cropped = frame_img.crop((sx, sy, sx + sw, sy + sh))
                        crop_file = crops_dir / f"{spec.name}_crop.png"
                        cropped.save(str(crop_file))
                        cropped_path = str(crop_file)
                except Exception as _e:
                    logger.warning(f"[DECOMPOSE] Crop failed for {spec.name}: {_e}")

            # 2. Generate via Claude — with retry and programmatic fallback
            code = self._generate_decomposed_component(spec, cropped_path, image_map)
            if not code:
                logger.warning(f"[DECOMPOSE] No code for {spec.name} — using programmatic fallback")
                code = self.code_generator.generate_component(spec.node, spec.name, image_map)

            # 3. Bracket/syntax validation — retry once on failure, then programmatic fallback
            code = re.sub(r'(return\s*\()[ \t]+(<)', r'\1\n    \2', code)
            if not AICodeGenerator._bracket_balance_check(code, spec.name):
                logger.warning(f"[DECOMPOSE] {spec.name}: bracket check failed — retrying with stricter prompt")
                retry_code = self._generate_decomposed_component(
                    spec, cropped_path, image_map,
                    extra_instruction=(
                        "\n\nCRITICAL: Your previous response had syntax errors. "
                        "Return ONLY valid TSX code. Ensure ALL tags are closed, "
                        "ALL parentheses are balanced, and the code compiles without errors."
                    ),
                )
                if retry_code and AICodeGenerator._bracket_balance_check(retry_code, spec.name):
                    code = re.sub(r'(return\s*\()[ \t]+(<)', r'\1\n    \2', retry_code)
                    logger.info(f"[DECOMPOSE] {spec.name}: retry succeeded")
                else:
                    logger.warning(f"[DECOMPOSE] {spec.name}: retry also failed — using programmatic fallback")
                    code = self.code_generator.generate_component(spec.node, spec.name, image_map)

            # 4. Save
            comp_file = components_dir / f"{spec.name}.tsx"
            comp_file.write_text(code, encoding="utf-8")
            logger.info(f"[DECOMPOSE] ✅ {spec.name}.tsx ({len(code)} chars)")
            generated_specs.append({"name": spec.name, "file": str(comp_file), "spec": spec})

        if not generated_specs:
            logger.warning(f"[DECOMPOSE] All generations failed for {comp_name}")
            return []

        # ── Page layout ──────────────────────────────────────────────────────
        page_name = f"{comp_name}Page"
        page_code = self._generate_decomposed_page_layout(page_name, specs, generated_specs, frame)
        page_file = components_dir / f"{page_name}.tsx"
        page_file.write_text(page_code, encoding="utf-8")
        logger.info(f"[DECOMPOSE] ✅ Page layout: {page_name}.tsx")

        # ── Full build check ─────────────────────────────────────────────────
        logger.info(f"[DECOMPOSE] Running next build to verify generated code…")
        try:
            build_result = subprocess.run(
                ["npx", "next", "build"],
                cwd=str(output_dir),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if build_result.returncode != 0:
                tail = (build_result.stdout + build_result.stderr)[-800:]
                logger.warning(f"[DECOMPOSE] Build FAILED — falling back to monolithic pipeline\n{tail}")
                return []  # triggers monolithic fallback in convert()
            logger.info(f"[DECOMPOSE] ✅ Build passed")
        except subprocess.TimeoutExpired:
            logger.warning("[DECOMPOSE] Build timed out — proceeding anyway (assume OK)")
        except Exception as _build_err:
            logger.warning(f"[DECOMPOSE] Build check error: {_build_err} — proceeding anyway")

        return [{
            "name": page_name,
            "file": str(page_file),
            "original": frame.name,
            "node_id": frame.id,
            "node_type": frame.type,
        }]

    def _generate_decomposed_component(
        self,
        spec,                           # ComponentSpec
        cropped_path: Optional[str],
        image_map: Dict[str, str],
        extra_instruction: str = "",    # appended on retry
    ) -> Optional[str]:
        """Call Claude with a cropped screenshot + structured description to generate one component."""
        if not self.ai_generator.anthropic_client and not self.ai_generator.groq_client:
            return None

        system_text = (
            "You are a pixel-perfect React + Tailwind CSS developer. "
            "Convert the Figma component to a TypeScript React component.\n\n"
            "RULES:\n"
            "- Output ONLY raw TSX — no markdown fences, no explanations\n"
            f"- The function MUST be named EXACTLY: {spec.name} (case-sensitive)\n"
            "- Tailwind CSS classes; for non-standard values use arbitrary: w-[340px], text-[13px]\n"
            "- Next.js <Image> for images (import Image from 'next/image'; width+height required)\n"
            "- Match the screenshot exactly: colors, spacing, typography, borders, shadows\n"
            "- Use exact hex colors from the node description\n"
            "- Escape { } inside JSX text with &#123; &#125;\n"
            "- ALL tags must be properly closed; ALL parentheses must be balanced"
        )

        tree_description = self._describe_node_for_prompt(spec.node, image_map)
        text_content = self._collect_text_content(spec.node)
        image_refs = self._collect_image_refs(spec.node, image_map)

        w = int(spec.node.width)
        h = int(spec.node.height)
        text_block = "\n".join(f'  "{t}"' for t in text_content[:30]) if text_content else "  (none)"
        image_block = "\n".join(f"  {r}" for r in image_refs[:10]) if image_refs else "  (none)"

        template_section = ""
        if spec.is_template and spec.instances:
            varying = "\n".join(f"  {k}: {repr(v)}" for k, v in list(spec.instances[0].items())[:10])
            template_section = (
                f"\nTEMPLATE: rendered ×{spec.instance_count}. "
                f"Define a TypeScript props interface for these varying fields:\n{varying}\n"
            )

        prompt_text = f"""Convert this Figma component to a React + Tailwind component.

COMPONENT TREE:
{tree_description}

ALL TEXT CONTENT (use exactly these strings):
{text_block}

IMAGE REFERENCES (use these exact paths):
{image_block}
{template_section}
RULES:
- Use exact pixel values from the tree: w-[{w}px], h-[{h}px]
- Use arbitrary Tailwind values: bg-[#1c1442], text-[14px], rounded-[10px], gap-[8px]
- Every TEXT node must appear in the output with its exact content
- Every IMAGE node must render as <img src="{{path}}" className="w-full h-full object-cover" alt="" />
- Use flex-row for HORIZONTAL layout, flex-col for VERTICAL
- Nodes without layoutMode use relative/absolute positioning
- Include ALL children shown in the tree, not just top-level ones
- The export MUST be exactly: export default function {spec.name}() (name is case-sensitive)
- Return ONLY the code, no markdown fences, no explanation{extra_instruction}"""

        # User message: text + optional screenshot crop
        user_content: List[Dict] = [{"type": "text", "text": prompt_text}]
        if cropped_path and Path(cropped_path).exists():
            try:
                import base64 as _b64
                b64 = _b64.b64encode(Path(cropped_path).read_bytes()).decode()
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                })
                user_content.append({
                    "type": "text",
                    "text": "Replicate the component shown in the image precisely.",
                })
            except Exception as _e:
                logger.warning(f"[DECOMPOSE] Could not encode crop for {spec.name}: {_e}")

        messages = [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_content},
        ]

        if self.ai_generator.anthropic_client:
            raw = self.ai_generator._call_claude(messages, max_tokens=4096)
        else:
            # Groq text-only fallback
            try:
                resp = self.ai_generator.groq_client.chat.completions.create(
                    model=self.ai_generator.model,
                    messages=[
                        {"role": "system", "content": system_text},
                        {"role": "user", "content": prompt_text},
                    ],
                    temperature=0.1,
                    max_tokens=4096,
                )
                raw = resp.choices[0].message.content
            except Exception as _e:
                logger.error(f"[DECOMPOSE] Groq fallback failed for {spec.name}: {_e}")
                return None

        if not raw:
            return None

        # Strip markdown code fences Claude sometimes wraps the response in
        code = raw.strip()
        if code.startswith("```"):
            code = code.split("\n", 1)[1] if "\n" in code else code[3:]
        if "```" in code:
            code = code[:code.rfind("```")]
        return code.strip()

    def _generate_decomposed_page_layout(
        self,
        page_name: str,
        specs,                  # List[ComponentSpec]
        generated: List[Dict],  # only successfully generated specs
        frame,                  # FigmaNode — for dimension hints
    ) -> str:
        """Programmatically compose a page layout that imports and renders sub-components."""
        generated_names = {d["name"] for d in generated}

        # Imports — deduplicated (same name must not be imported twice)
        imported: set = set()
        import_lines: List[str] = []
        for s in specs:
            if s.name in generated_names and s.name not in imported:
                import_lines.append(f"import {s.name} from './{s.name}'")
                imported.add(s.name)

        # Detect sidebar: any layout_region narrower than 32% of frame width
        has_sidebar = any(
            s.component_type == "layout_region" and s.node.width < frame.width * 0.32
            for s in specs if s.name in generated_names
        )

        # Data declarations — only for templates that have actual per-instance diffs
        data_decls: List[str] = []
        for spec in specs:
            if spec.name not in generated_names or not spec.is_template:
                continue
            non_empty = [inst for inst in spec.instances if inst]
            if not non_empty:
                continue  # no diffs — will render N plain tags instead
            var = spec.name[0].lower() + spec.name[1:] + "Data"
            entries = [
                "  { id: " + str(i) + ", " + ", ".join(f"{k}: {repr(v)}" for k, v in inst.items()) + " }"
                for i, inst in enumerate(non_empty)
            ]
            data_decls.append(f"const {var} = [\n" + ",\n".join(entries) + "\n]")

        # Render expressions — use a parallel list of (render_str, spec) for layout splitting
        render_pairs: List[tuple] = []   # (render_str, spec)
        rendered_names: set = set()      # guard against double-rendering
        for spec in specs:
            if spec.name not in generated_names or spec.name in rendered_names:
                continue
            rendered_names.add(spec.name)
            if spec.is_template:
                non_empty = [inst for inst in spec.instances if inst]
                if non_empty:
                    # Map over data array
                    var = spec.name[0].lower() + spec.name[1:] + "Data"
                    render_str = (
                        f"      {{{var}.map((item) => (\n"
                        f"        <{spec.name} key={{item.id}} {{...item}} />\n"
                        f"      ))}}"
                    )
                else:
                    # No varying data — render N plain instances
                    render_str = "\n".join(
                        f"      <{spec.name} />" for _ in range(spec.instance_count)
                    )
            else:
                render_str = f"      <{spec.name} />"
            render_pairs.append((render_str, spec))

        # Layout wrapper
        if has_sidebar:
            sidebar_names = {
                s.name for s in specs
                if s.component_type == "layout_region"
                and s.node.width < frame.width * 0.32
                and s.name in generated_names
            }
            sidebar_renders = [r for r, s in render_pairs if s.name in sidebar_names]
            other_renders   = [r for r, s in render_pairs if s.name not in sidebar_names]
            body = (
                '    <div className="flex h-screen overflow-hidden">\n'
                + "\n".join(sidebar_renders) + "\n"
                + '      <div className="flex-1 flex flex-col overflow-hidden">\n'
                + "\n".join(other_renders) + "\n"
                + '      </div>\n'
                + '    </div>'
            )
        else:
            body = (
                '    <div className="w-full">\n'
                + "\n".join(r for r, _ in render_pairs) + "\n"
                + '    </div>'
            )

        data_block = ("\n\n" + "\n\n".join(data_decls)) if data_decls else ""
        return (
            "\n".join(import_lines)
            + data_block
            + f"\n\nexport default function {page_name}() {{\n"
            + "  return (\n"
            + body + "\n"
            + "  )\n"
            + "}\n"
        )

    def _describe_node_for_prompt(self, node, image_map: Dict[str, str], depth: int = 0, max_depth: int = 5) -> str:
        """Recursive tree description of a FigmaNode for the AI prompt."""
        indent = "  " * depth
        raw = node.raw if hasattr(node, 'raw') and node.raw else {}
        type_str = raw.get("type", node.type or "FRAME")
        name = raw.get("name", node.name or "")
        w = int(node.width)
        h = int(node.height)
        line = f'{indent}{type_str} "{name}" {w}x{h}'

        # Layout
        layout = raw.get("layoutMode")
        if layout and layout != "NONE":
            gap = raw.get("itemSpacing", 0)
            line += f" layout={layout} gap={gap}"

        # Background color (first solid fill)
        fills = raw.get("fills", [])
        if isinstance(fills, list):
            for f in fills:
                if isinstance(f, dict) and f.get("type") == "SOLID" and f.get("visible", True):
                    c = f.get("color", {})
                    r, g, b = int(c.get("r", 0) * 255), int(c.get("g", 0) * 255), int(c.get("b", 0) * 255)
                    line += f" bg=#{r:02x}{g:02x}{b:02x}"
                    break
                if isinstance(f, dict) and f.get("type") == "IMAGE" and f.get("visible", True):
                    ref = f.get("imageRef", "")
                    img_path = image_map.get(ref, image_map.get(node.id, ""))
                    if img_path:
                        line += f' image="{img_path}"'
                    else:
                        line += " image=<fill>"
                    break

        # Corner radius
        radius = raw.get("cornerRadius")
        if radius:
            line += f" rounded={radius}"

        # Text node: content + typography
        if type_str == "TEXT":
            chars = raw.get("characters", "")
            style = raw.get("style", {})
            fs = style.get("fontSize", "")
            fw = style.get("fontWeight", "")
            line += f' text="{chars[:80]}"'
            if fs:
                line += f" size={fs}"
            if fw:
                line += f" weight={fw}"

        # Clipping / opacity
        if raw.get("clipsContent"):
            line += " clip=true"
        opacity = raw.get("opacity")
        if opacity is not None and opacity < 1:
            line += f" opacity={opacity:.2f}"

        lines = [line]

        # Recurse into visible children
        if depth < max_depth and hasattr(node, 'children'):
            for child in node.children:
                if child.raw.get("visible", True) if hasattr(child, 'raw') and child.raw else True:
                    lines.append(self._describe_node_for_prompt(child, image_map, depth + 1, max_depth))

        return "\n".join(lines)

    @staticmethod
    def _describe_fills(fills: List[Dict]) -> str:
        """Convert a fills list to a human-readable color/gradient string."""
        parts: List[str] = []
        for f in fills:
            if not isinstance(f, dict) or not f.get("visible", True):
                continue
            ftype = f.get("type")
            if ftype == "SOLID":
                c = f.get("color", {})
                r, g, b = int(c.get("r", 0) * 255), int(c.get("g", 0) * 255), int(c.get("b", 0) * 255)
                a = f.get("opacity", c.get("a", 1.0))
                parts.append(f"#{r:02x}{g:02x}{b:02x}" + (f" (opacity {a:.2f})" if a < 0.99 else ""))
            elif ftype == "GRADIENT_LINEAR":
                stops = f.get("gradientStops", [])
                stop_colors = []
                for s in stops[:2]:
                    c = s.get("color", {})
                    r, g, b = int(c.get("r", 0) * 255), int(c.get("g", 0) * 255), int(c.get("b", 0) * 255)
                    stop_colors.append(f"#{r:02x}{g:02x}{b:02x}")
                parts.append(f"linear-gradient({' → '.join(stop_colors)})")
            elif ftype == "IMAGE":
                parts.append("image-fill")
        return ", ".join(parts)

    @staticmethod
    def _collect_text_content(node) -> List[str]:
        """Walk the subtree and collect all non-empty TEXT node characters."""
        texts: List[str] = []
        def _walk(n) -> None:
            if n.type == "TEXT" and n.characters:
                texts.append(n.characters.strip())
            for child in n.children:
                _walk(child)
        _walk(node)
        return texts

    @staticmethod
    def _collect_image_refs(node, image_map: Dict[str, str]) -> List[str]:
        """Walk the subtree and return image paths present in image_map."""
        refs: List[str] = []
        seen: set = set()
        def _walk(n) -> None:
            if n.id in image_map and n.id not in seen:
                refs.append(image_map[n.id])
                seen.add(n.id)
            for child in n.children:
                _walk(child)
        _walk(node)
        return refs

    # ──────────────────────────────────────────────────────────────────────────

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
        headers = {"X-Figma-Token": self.figma_token.strip()}
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
        """Return the frames to convert.

        Normally returns every top-level FRAME across all pages.
        When self._target_node_id is set (from a ?node-id= URL param), searches
        the full document tree for that node and narrows the result:
          - FRAME node  → [node]
          - GROUP/SECTION → direct FRAME children of that node
        Falls back to all frames if the node is not found or is too small (< 300px).
        """
        # Collect all top-level frames (baseline result)
        frames: List[FigmaNode] = []
        for page in root.children:
            for child in page.children:
                if child.type == "FRAME" and child.visible:
                    frames.append(child)

        logger.info(
            f"[_get_frames] Found {len(frames)} top-level frames:\n"
            + "\n".join(
                f"  [{i}] id={f.id!r:20s} {int(f.width):5d}x{int(f.height):<5d}  name={f.name!r}"
                for i, f in enumerate(frames)
            )
        )

        target_id: Optional[str] = getattr(self, '_target_node_id', None)
        if not target_id:
            return frames

        # Search full tree for the target node
        def _find(node: FigmaNode, wanted: str) -> Optional[FigmaNode]:
            if node.id == wanted:
                return node
            for child in node.children:
                found = _find(child, wanted)
                if found:
                    return found
            return None

        target = _find(root, target_id)

        if target is None:
            logger.warning(f"node-id {target_id!r} not found in document — returning all frames")
            return frames

        if target.width <= 300 or target.height <= 300:
            logger.warning(
                f"node-id {target_id!r} ({target.name}) is {int(target.width)}×{int(target.height)}px"
                " — too small to use as a frame target, returning all frames"
            )
            return frames

        if target.type == "FRAME":
            logger.info(
                f"Targeting node {target_id!r} ({target.name} "
                f"{int(target.width)}×{int(target.height)})"
            )
            return [target]

        if target.type in ("GROUP", "SECTION"):
            children = [c for c in target.children if c.type == "FRAME" and c.visible]
            if children:
                logger.info(
                    f"Targeting node {target_id!r} ({target.name} "
                    f"{int(target.width)}×{int(target.height)}) — "
                    f"using {len(children)} FRAME children"
                )
                return children

        logger.warning(
            f"node-id {target_id!r} ({target.name}, type={target.type}) yielded no usable frames"
            " — returning all frames"
        )
        return frames
    
    def _extract_file_id(self, url: str) -> Tuple[str, Optional[str]]:
        """Extract (file_id, node_id) from a Figma URL.

        node_id is parsed from ?node-id=X-Y or ?node-id=X%3AY (URL-encoded colon).
        Returns (file_id, None) when no node-id query param is present.
        """
        file_id: Optional[str] = None
        for pattern in (r'/design/([a-zA-Z0-9]+)', r'/file/([a-zA-Z0-9]+)'):
            m = re.search(pattern, url)
            if m:
                file_id = m.group(1)
                break
        if not file_id:
            raise Exception("Invalid Figma URL")

        node_id: Optional[str] = None
        nid_match = re.search(r'[?&]node-id=([^&]+)', url)
        if nid_match:
            raw = nid_match.group(1)
            # X%3AY → X:Y  (URL-encoded colon);  X-Y stays as X:Y (Figma dash form)
            node_id = raw.replace('%3A', ':').replace('-', ':')

        return file_id, node_id
    
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

        # Generate globals.css with Tailwind directives.
        # Do NOT set overflow:hidden on html/body — it breaks landing pages.
        # Dashboard components manage their own scroll via overflow-hidden/overflow-y-auto.
        globals_css = '''@tailwind base;
@tailwind components;
@tailwind utilities;

html,
body {
  margin: 0;
  padding: 0;
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
    
    def _generate_tailwind_config(self, output_dir: Path, color_tokens: Dict = None):
        """Generate tailwind.config.js with extracted design-token colors in theme.extend."""
        # Build the colors block from extracted tokens so Tailwind knows about
        # `bg-background`, `text-text-primary`, `bg-primary`, etc.
        color_lines: List[str] = []
        if color_tokens:
            for key, val in color_tokens.items():
                if isinstance(val, dict):
                    inner = ", ".join(f"'{k}': '{v}'" for k, v in val.items())
                    color_lines.append(f"        '{key}': {{ {inner} }},")
                else:
                    color_lines.append(f"        '{key}': '{val}',")

        extend_block: List[str] = ["    extend: {"]
        if color_lines:
            extend_block.append("      colors: {")
            extend_block.extend(color_lines)
            extend_block.append("      },")
        extend_block.append("    },")

        config_lines = [
            "/** @type {import('tailwindcss').Config} */",
            "module.exports = {",
            "  content: [",
            "    './src/**/*.{js,ts,jsx,tsx,mdx}',",
            "  ],",
            "  theme: {",
        ] + extend_block + [
            "  },",
            "  plugins: [],",
            "}",
            "",
        ]

        with open(output_dir / "tailwind.config.js", "w", encoding="utf-8") as f:
            f.write("\n".join(config_lines))

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