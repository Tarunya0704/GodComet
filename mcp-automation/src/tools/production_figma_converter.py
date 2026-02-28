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
        return any(f.get("type") == "SOLID" and f.get("visible", True) for f in node.fills)

    @staticmethod
    def _has_image_fill(node: FigmaNode) -> bool:
        return any(f.get("type") == "IMAGE" and f.get("visible", True) for f in node.fills)


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
        if parent is not None and parent.has_auto_layout:
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

        # Background — some node types must NOT get bg-[#hex] from their fills:
        #   TEXT            → fills are text colour, handled by get_text_classes()
        #   VECTOR          → fills are SVG path colours (icon ink), not CSS backgrounds;
        #                     mapping them to bg-[#hex] produces solid black squares
        #   BOOLEAN_OPERATION → same as VECTOR (composed SVG paths)
        _NO_BG_TYPES = {"TEXT", "VECTOR", "BOOLEAN_OPERATION"}
        if node.type not in _NO_BG_TYPES and node.fills and len(node.fills) > 0:
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
        self.figma_token = figma_token.strip()  # strip whitespace/newlines from .env
        self.api_base = "https://api.figma.com/v1"

    async def download_images(self, file_id: str, nodes: List[FigmaNode], output_dir: Path) -> Dict[str, str]:
        """Download all images and return mapping of node_id -> local_path.

        Images are cached on disk by node-ID filename.  On subsequent runs the
        Figma API is only called for nodes whose file is genuinely missing — this
        avoids the 403 (expired S3 URL) and 429 (rate limit) errors that occur
        when the full set is re-requested against a stale Figma file cache.
        """
        # Collect all nodes with image fills
        image_nodes = []
        for node in nodes:
            if self._has_image_fill(node):
                image_nodes.append(node)

        if not image_nodes:
            return {}

        images_dir = output_dir / "public" / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        # ── Pass 1: serve from disk cache ────────────────────────────────────
        image_map: Dict[str, str] = {}
        missing_nodes: List[FigmaNode] = []

        for node in image_nodes:
            safe_id = node.id.replace(':', '_').replace('/', '_')
            filename = f"{safe_id}.png"
            filepath = images_dir / filename
            if filepath.exists() and filepath.stat().st_size > 0:
                image_map[node.id] = f"/images/{filename}"
                logger.debug(f"Cached image: {filename}")
            else:
                missing_nodes.append(node)

        if not missing_nodes:
            logger.info(f"All {len(image_map)} images served from disk cache — skipping Figma API")
            return image_map

        logger.info(f"{len(image_map)} cached, {len(missing_nodes)} need downloading")

        # ── Pass 2: fetch fresh URLs only for missing files ───────────────────
        node_ids = [n.id for n in missing_nodes]
        image_urls = await self._fetch_image_urls(file_id, node_ids)

        async with aiohttp.ClientSession() as session:
            for node in missing_nodes:
                safe_id = node.id.replace(':', '_').replace('/', '_')
                filename = f"{safe_id}.png"
                filepath = images_dir / filename

                url = image_urls.get(node.id)
                if not url:
                    logger.debug(f"No URL returned by Figma for node {node.id}")
                    continue

                await self._download_file(session, url, filepath)

                if filepath.exists() and filepath.stat().st_size > 0:
                    image_map[node.id] = f"/images/{filename}"
                    logger.info(f"Downloaded image: {filename}")
                else:
                    logger.warning(f"Image download empty/failed for {node.id}")

        logger.info(f"Image download complete: {len(image_map)}/{len(image_nodes)} images available")
        return image_map
    
    def _has_image_fill(self, node: FigmaNode) -> bool:
        """Check if node has image fill"""
        for fill in node.fills:
            if fill.get("type") == "IMAGE":
                return True
        return False
    
    async def _fetch_image_urls(self, file_id: str, node_ids: List[str]) -> Dict[str, str]:
        """Fetch image export URLs from Figma API.

        Uses the synchronous `requests` library (same as _fetch_file which works reliably)
        rather than aiohttp to avoid header-encoding differences.
        Token is stripped of whitespace before use.
        Retries on 429; tries both X-Figma-Token and Authorization: Bearer on 403.
        """
        if not node_ids:
            return {}

        # Strip token to eliminate any .env whitespace / newline issues
        token = self.figma_token.strip()

        header_variants = [
            {"X-Figma-Token": token},
            {"Authorization": f"Bearer {token}"},
        ]

        ids_param = ",".join(node_ids[:100])
        url = f"{self.api_base}/images/{file_id}"
        params = {"ids": ids_param, "format": "png", "scale": "2"}

        max_retries = 3
        loop = asyncio.get_event_loop()

        for attempt in range(max_retries):
            for headers in header_variants:
                header_label = "X-Figma-Token" if "X-Figma-Token" in headers else "Authorization: Bearer"
                try:
                    # Run synchronous requests.get in executor to avoid blocking event loop
                    def _do_get():
                        return requests.get(url, headers=headers, params=params, timeout=30)

                    response = await loop.run_in_executor(None, _do_get)

                    if response.status_code == 200:
                        return response.json().get("images", {})

                    if response.status_code == 403:
                        logger.warning(
                            f"Image API 403 with header {header_label}"
                            f" — response body: {response.text[:500]}"
                        )
                        continue  # try next header variant

                    if response.status_code == 429:
                        wait = min(60, 15 * (2 ** attempt))
                        logger.warning(
                            f"Image API rate limit (429). "
                            f"Waiting {wait}s (attempt {attempt + 1}/{max_retries})"
                        )
                        await asyncio.sleep(wait)
                        break  # break header loop, retry outer attempt

                    logger.warning(f"Image fetch returned {response.status_code}: {response.text[:200]}")
                    return {}

                except Exception as e:
                    logger.warning(f"Image fetch attempt {attempt + 1} ({header_label}) failed: {e}")

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
        
    def _infer_top_layout(self, root: FigmaNode) -> bool:
        """Detect sidebar+content pattern and mutate nodes to enable flex generation.

        When a Figma frame has no auto-layout the programmatic generator falls back
        to absolute pixel coordinates, producing a broken-looking page.  This method
        inspects the direct children's dimensions and, when it finds a narrow+tall
        (sidebar) child alongside a wide+tall (content) child, switches the root
        frame to HORIZONTAL flex in-memory so that the existing Tailwind path emits
        the correct flex classes rather than `absolute left-[X]px top-[Y]px`.

        Nothing is hardcoded — only relative dimension ratios are used.
        Returns True if inference was applied.
        """
        if root.has_auto_layout:
            return False  # already has explicit layout

        visible = [c for c in root.children if c.visible]
        if not (2 <= len(visible) <= 6):
            return False

        total_w = root.width or 1440
        total_h = root.height or 900

        sidebar_node = None
        content_node = None

        for child in visible[:5]:
            w, h = child.width, child.height
            if w > 0 and h > 0 and w < total_w * 0.28 and h > total_h * 0.70:
                if sidebar_node is None:
                    sidebar_node = child
            elif w > total_w * 0.50 and h > total_h * 0.50:
                if content_node is None:
                    content_node = child

        if not (sidebar_node and content_node):
            return False

        # ── Root: horizontal flex, full viewport ─────────────────────────────
        root.layout_mode = "HORIZONTAL"
        root.primary_axis_align = "MIN"
        root.counter_axis_align = "MIN"
        root.primary_axis_sizing = "FILL"   # → w-full
        root.counter_axis_sizing = "FILL"   # → h-full; _infer_hscreen upgrades to h-screen
        root._infer_hscreen = True          # signal: replace h-full with h-screen overflow-hidden

        # ── Sidebar: vertical flex, fixed width, full height ─────────────────
        sidebar_node.layout_mode = "VERTICAL"
        sidebar_node.primary_axis_sizing = "FILL"    # → h-full
        sidebar_node.counter_axis_sizing = "FIXED"   # → w-[Xpx] (keeps original Figma width)
        sidebar_node.layout_sizing_h = "FIXED"       # child-sizing: exact pixel width
        sidebar_node.layout_sizing_v = "FILL"        # child-sizing: full height
        sidebar_node._infer_shrink_0 = True           # signal: add flex-shrink-0

        # ── Content: vertical flex, fills remaining width ────────────────────
        content_node.layout_mode = "VERTICAL"
        content_node.primary_axis_sizing = "FILL"    # → h-full
        content_node.counter_axis_sizing = "FILL"    # → w-full; _infer_flex_one upgrades to flex-1
        content_node.layout_sizing_h = "FILL"        # child-sizing: fill remaining width
        content_node.layout_sizing_v = "FILL"        # child-sizing: full height
        content_node._infer_flex_one = True           # signal: use flex-1 min-w-0

        logger.info(
            f"[Layout Inference] sidebar='{sidebar_node.name}' (w={int(sidebar_node.width)}px)"
            f" + content='{content_node.name}' → flex h-screen"
        )
        return True

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
        self._infer_top_layout(node)  # detect sidebar+content and switch to flex before JSX gen

        # Generate imports
        imports = ["import React from 'react'"]
        if any(n.id in image_map for n in self._get_all_nodes(node)):
            imports.append("import Image from 'next/image'")
        imports_str = "\n".join(imports)

        # ── Fix 2: section-by-section for tall landing-page frames ───────────
        # Criteria: frame is tall (> 1200px), has no auto-layout (absolute coords),
        # and no sidebar was detected (not a dashboard).
        is_tall_page = (
            node.height > 1200
            and not node.has_auto_layout
            and not getattr(node, '_infer_hscreen', False)
        )
        visible_children = [c for c in node.children if c.visible]

        if is_tall_page and len(visible_children) >= 2:
            section_consts = []
            section_names = []
            for i, child in enumerate(visible_children):
                sec_name = f"Section{i}"
                section_names.append(sec_name)
                # Each child generated with parent=None so no parent-relative absolute coords
                jsx = self._generate_jsx(child, image_map, indent=2, parent=None)
                section_consts.append(f"const {sec_name} = () => (\n{jsx}\n)")

            renders = "\n      ".join(f"<{n} />" for n in section_names)
            sections_str = "\n\n".join(section_consts)

            logger.info(
                f"[Section Split] {component_name}: {len(visible_children)} sections "
                f"from {int(node.height)}px tall frame"
            )
            return f'''{imports_str}

{sections_str}

export default function {component_name}() {{
  return (
    <div className="w-full">
      {renders}
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

        # --- BUG 4 FIX: absolute positioning when parent has no auto-layout ---
        # Skip for children of a grid container — the grid handles positioning.
        if (parent is not None
                and not parent.has_auto_layout
                and not getattr(parent, '_infer_grid', False)
                and node.absolute_bounds):
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

        # ── Apply layout-inference overrides (set by _infer_top_layout) ──────
        # These flags are set in-memory and override whatever the standard
        # Tailwind converters produced, without touching any Figma data.
        if getattr(node, '_infer_hscreen', False):
            # Root flex container: replace any fixed/relative height with h-screen
            classes = [c for c in classes if not (c.startswith('h-[') or c == 'h-full')]
            classes.extend(['h-screen', 'overflow-hidden'])

        if getattr(node, '_infer_shrink_0', False):
            classes.append('flex-shrink-0')

        if getattr(node, '_infer_flex_one', False):
            # Content panel fills remaining width — flex-1 beats w-full in a flex row
            classes = [c for c in classes if not (c.startswith('w-[') or c == 'w-full')]
            classes.extend(['flex-1', 'min-w-0'])

        # Fix 1: root container (parent is None) must never block page scroll.
        # Replace overflow-hidden with overflow-y-auto so a landing page can scroll.
        # Dashboards: their root is h-screen so no overflow actually occurs anyway.
        if parent is None and 'overflow-hidden' in classes:
            classes = [c if c != 'overflow-hidden' else 'overflow-y-auto' for c in classes]

        # Build className string
        class_str = " ".join(classes)

        # Opening tag
        if element == "img":
            # Next.js Image component — skip if no valid src (empty src crashes build)
            img_src = image_map.get(node.id, "")
            if not img_src:
                # Grey placeholder — preserves card structure and keeps white text
                # readable while the actual image is unavailable (e.g. 403 from Figma).
                # bg-gray-300 is a generic convention, not design-specific.
                placeholder_cls = (f"{class_str} bg-gray-300 animate-pulse").strip()
                lines.append(f'{ind}<div className="{placeholder_cls}" />')
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
        figma_screenshot_path: str = None,
        layout_type: str = "dashboard",
    ) -> Optional[str]:
        """Generate component code using AI vision model"""
        if not self.groq_client:
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

        # Load screenshot once
        img_b64: Optional[str] = None
        if figma_screenshot_path and Path(figma_screenshot_path).exists():
            import base64
            with open(figma_screenshot_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode()

        enhanced_sections: List[str] = []

        for i, sec_code in enumerate(section_codes):
            logger.info(
                f"🎨 [AI ENHANCE] {component_name} section {i + 1}/{len(section_codes)} "
                f"({len(sec_code)} chars)"
            )
            prompt = (
                f"This is section {i + 1} of {len(section_codes)} from a landing page. "
                "Fix ONLY visual details visible in the screenshot "
                "(gradients, shadows, border-radius, font weights). "
                "DO NOT restructure or rename anything. "
                "Return ONLY the corrected const arrow function — same form as input."
                + token_hint
                + f"\n\nSection code:\n{sec_code}"
            )

            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a visual QA engineer. Return ONLY the corrected "
                        "const arrow function — no markdown fences, no explanation."
                    ),
                }
            ]
            if img_b64:
                messages.append({
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                        {"type": "text", "text": prompt},
                    ],
                })
            else:
                messages.append({"role": "user", "content": prompt})

            try:
                resp = self.groq_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.1,
                    max_tokens=8192,
                )
                enhanced_sec = resp.choices[0].message.content
                if "```" in enhanced_sec:
                    m = re.search(r'```(?:tsx|jsx|typescript|javascript)?\n(.*?)```', enhanced_sec, re.DOTALL)
                    if m:
                        enhanced_sec = m.group(1).strip()
                # Validate: must still be the same section const
                if f'const Section{i}' not in enhanced_sec:
                    logger.warning(f"Section {i} enhancement lost const name — keeping original")
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
        if not self.groq_client:
            return None

        # Fix 3: for large sectioned components, enhance section-by-section so
        # each AI call stays well within the 8192 output-token limit.
        if len(deterministic_code) > 15000:
            split = self._split_into_sections(deterministic_code)
            if split:
                logger.info(
                    f"[Section Enhance] {component_name}: "
                    f"{len(split[1])} sections, total {len(deterministic_code)} chars"
                )
                result = self._enhance_by_sections(split, component_name, figma_screenshot_path, token_colors)
                if result:
                    return result

        try:
            # Build optional token hint so AI knows what semantic names are available
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
                    "\n\nDesign tokens extracted from this Figma file (available as Tailwind class names):\n"
                    + "\n".join(flat)
                    + "\nWhen adding NEW color classes for visual fixes, prefer the semantic token names "
                    "(e.g. `bg-background`, `text-text-primary`, `bg-primary`) over raw hex values.\n"
                )

            enhance_prompt = (
                "Here is programmatically generated TSX built from exact Figma measurements "
                "(correct flex/grid structure, exact pixel sizes, exact hex colors). "
                "Compare it against the screenshot and fix ONLY what looks visually wrong:\n"
                "  • Gradient backgrounds (replace solid color with gradient if the screenshot shows one)\n"
                "  • Complex drop shadows or box-shadows\n"
                "  • Missing overlay gradients on images\n"
                "  • Border styles or radii that differ from the screenshot\n"
                "  • Font weight / letter-spacing / line-height mismatches\n"
                "  • Missing visual effects (blur, opacity layers)\n\n"
                "DO NOT change:\n"
                "  • The flex/grid layout structure or element hierarchy\n"
                "  • Any w-[Xpx], h-[Xpx], gap-[Xpx], p-[Xpx] classes\n"
                "  • Any bg-[#rrggbb] or text-[#rrggbb] classes that already match the screenshot\n"
                "  • The export default function signature\n"
                + token_hint
                + "\nReturn the complete corrected TSX only — no markdown fences, no explanation.\n\n"
                f"TSX to enhance:\n{deterministic_code}"
            )

            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a visual QA engineer for React/Tailwind code. "
                        "You receive deterministic TSX and a Figma screenshot. "
                        "You output ONLY corrected raw TSX — no markdown, no comments, no explanation."
                    ),
                }
            ]

            if figma_screenshot_path and Path(figma_screenshot_path).exists():
                import base64
                with open(figma_screenshot_path, "rb") as f:
                    img_b64 = base64.b64encode(f.read()).decode()
                messages.append({
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                        {"type": "text", "text": enhance_prompt},
                    ],
                })
            else:
                messages.append({"role": "user", "content": enhance_prompt})

            logger.info(f"🎨 [AI ENHANCE] Enhancing {component_name} visual details")
            response = self.groq_client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.1,
                max_tokens=8192,
            )

            enhanced = response.choices[0].message.content

            # Strip markdown fences if present
            if "```" in enhanced:
                match = re.search(r'```(?:tsx|jsx|typescript|javascript)?\n(.*?)```', enhanced, re.DOTALL)
                if match:
                    enhanced = match.group(1).strip()

            # Sanity-check 1: must still have export default
            if "export default" not in enhanced:
                logger.warning("AI enhance returned code without export default — discarding")
                return None

            # Sanity-check 2: truncation guard — output must end with a closing brace.
            # If max_tokens was hit mid-output the file ends with open tags/braces,
            # which causes "Unexpected token" errors at build time.
            if enhanced.rstrip()[-1] != '}':
                logger.warning("AI enhance output is truncated (doesn't end with '}') — discarding")
                return None

            # Sanity-check 3: brace balance — open { must equal close }
            if enhanced.count('{') != enhanced.count('}'):
                logger.warning(
                    f"AI enhance output has unbalanced braces "
                    f"({{ {enhanced.count('{')}  }} {enhanced.count('}')}) — discarding"
                )
                return None

            logger.info(f"✅ [AI ENHANCE] {component_name} enhanced ({len(enhanced)} chars)")
            return enhanced

        except Exception as e:
            logger.error(f"AI enhance failed: {e}")
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
            headers = {"X-Figma-Token": self.figma_token.strip()}
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
                            token_colors=self.token_extractor.build_tokens().get("colors", {}),
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
            self._generate_tailwind_config(
                output_dir,
                self.token_extractor.build_tokens().get("colors", {}),
            )
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