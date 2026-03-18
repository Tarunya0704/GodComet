"""
ComponentDecomposer — splits a Figma frame into independently generatable components.

Decomposition hierarchy (evaluated in order, highest priority first):
  1. Layout regions  — sidebar, header, main content (structural backbone)
  2. Repeated patterns — 3+ siblings with similar dimensions → single template + N instances
  3. Self-contained sections — auto-layout direct children of content area
  4. Leaf components — small reusable elements (Button, Badge, Card) via ComponentClassifier

Each ComponentSpec carries everything the code generator needs:
  - the FigmaNode subtree
  - a crop_box for slicing the frame screenshot
  - per-instance data dict for repeated templates
"""

import re
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class RepeatedPattern:
    """A group of sibling nodes with similar dimensions."""
    template: "FigmaNode"
    instances: List["FigmaNode"]
    per_instance_data: List[Dict]


@dataclass
class ComponentSpec:
    """Everything the code generator needs to produce one component."""
    name: str
    node: "FigmaNode"
    component_type: str                    # "layout_region" | "repeated_pattern" | "section" | "leaf"
    crop_box: Tuple[int, int, int, int]   # (x, y, w, h) relative to the frame's top-left corner
    is_template: bool = False
    instances: List[Dict] = field(default_factory=list)
    instance_count: int = 1
    cols_per_row: int = 0   # >0 = use CSS grid with this many columns; 0 = unknown
    gap_px: int = 0         # pixel gap between grid cells (derived from Figma spacing)


# ---------------------------------------------------------------------------
# ComponentDecomposer
# ---------------------------------------------------------------------------

# Names that Figma auto-generates and that carry no semantic meaning.
_AUTO_GENERATED_RE = re.compile(
    r'^(Frame|Group|Rectangle|Vector|Ellipse|Instance|Component|Section|'
    r'Polygon|Star|Line|Arrow|BooleanOperation)\s*\d*$',
    re.IGNORECASE,
)


class ComponentDecomposer:
    """
    Walks a FigmaNode tree and returns an ordered list of ComponentSpec objects
    suitable for independent code generation.

    Usage:
        decomposer = ComponentDecomposer()
        specs = decomposer.decompose(root_frame_node)
    """

    _DIM_TOLERANCE = 0.10    # ±10% for repeated-pattern detection
    _DUP_TOLERANCE = 0.15    # ±15% for same-name deduplication
    _MIN_PATTERN_SIZE = 3

    def __init__(self):
        try:
            from tools.production_figma_converter import ComponentClassifier as _CC
            self._classifier = _CC()
        except ImportError:
            try:
                from production_figma_converter import ComponentClassifier as _CC
                self._classifier = _CC()
            except ImportError:
                self._classifier = None

        # State reset at each decompose() call
        self._section_counter = 0
        self._frame_x = self._frame_y = 0.0
        self._frame_w = self._frame_h = 1.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def decompose(self, root: "FigmaNode") -> List[ComponentSpec]:
        """
        Decompose *root* (a frame-level FigmaNode) into ComponentSpec objects.
        Returns specs ordered: layout regions → sections → patterns → leaves.
        """
        # Reset per-call state
        self._section_counter = 0
        self._frame_x = root.absolute_bounds.get("x", 0) if root.absolute_bounds else 0
        self._frame_y = root.absolute_bounds.get("y", 0) if root.absolute_bounds else 0
        self._frame_w = root.width or 1440
        self._frame_h = root.height or 900

        specs: List[ComponentSpec] = []
        seen_ids: set = set()
        visible = [c for c in root.children if c.visible]

        # ── 1. Layout regions ─────────────────────────────────────────────────
        layout_specs, sidebar_node, content_nodes = self._decompose_layout_regions(
            root, visible
        )
        for s in layout_specs:
            specs.append(s)
            seen_ids.add(s.node.id)

        # ── 2. Repeated patterns ──────────────────────────────────────────────
        pattern_search = content_nodes if content_nodes else visible
        for pat in self._find_repeated_patterns(pattern_search):
            if pat.template.id in seen_ids:
                continue
            specs.append(self._pattern_to_spec(pat))
            for inst in pat.instances:
                seen_ids.add(inst.id)

        # ── 3. Self-contained sections ────────────────────────────────────────
        for node in (content_nodes if content_nodes else visible):
            if node.id in seen_ids:
                continue
            if self._is_self_contained_section(node):
                specs.append(self._node_to_spec(node, "section"))
                seen_ids.add(node.id)

        # ── 4. Leaf components ────────────────────────────────────────────────
        specs.extend(self._find_leaf_components(root, seen_ids))

        # ── 5. Deduplication + final uniqueness pass ──────────────────────────
        specs = self._deduplicate_specs(specs)

        logger.info(
            f"[Decomposer] '{root.name}': {len(specs)} components — "
            f"{sum(1 for s in specs if s.component_type == 'layout_region')} layout, "
            f"{sum(1 for s in specs if s.component_type == 'repeated_pattern')} patterns, "
            f"{sum(1 for s in specs if s.component_type == 'section')} sections, "
            f"{sum(1 for s in specs if s.component_type == 'leaf')} leaves"
        )
        return specs

    # ------------------------------------------------------------------
    # 1. Layout region detection
    # ------------------------------------------------------------------

    def _decompose_layout_regions(
        self,
        root: "FigmaNode",
        visible: List["FigmaNode"],
    ) -> Tuple[List[ComponentSpec], Optional["FigmaNode"], List["FigmaNode"]]:
        """Detect sidebar / header and return (specs, sidebar_node, content_nodes)."""
        specs: List[ComponentSpec] = []
        sidebar_node: Optional["FigmaNode"] = None
        header_node: Optional["FigmaNode"] = None

        root_x = root.absolute_bounds.get("x", 0) if root.absolute_bounds else 0

        # Sidebar: leftmost, narrow (<32% wide), tall (>30% frame height)
        for child in visible:
            if not child.absolute_bounds:
                continue
            rel_x = child.absolute_bounds.get("x", 0) - root_x
            w, h = child.width, child.height
            if (w > 0 and h > 0
                    and rel_x < self._frame_w * 0.05
                    and w < self._frame_w * 0.32
                    and h > self._frame_h * 0.30):
                sidebar_node = child
                break

        # Header: full-width (>70%), short (<15% tall), near top (<15% from top)
        root_y = root.absolute_bounds.get("y", 0) if root.absolute_bounds else 0
        for child in visible:
            if child is sidebar_node:
                continue
            w, h = child.width, child.height
            if w > self._frame_w * 0.70 and 0 < h < self._frame_h * 0.15:
                rel_y = (child.absolute_bounds.get("y", 0) if child.absolute_bounds else 0) - root_y
                if rel_y < self._frame_h * 0.15:
                    header_node = child
                    break

        if sidebar_node:
            specs.append(self._node_to_spec(sidebar_node, "layout_region", role="sidebar"))
        if header_node:
            specs.append(self._node_to_spec(header_node, "layout_region", role="header"))

        excluded = {n.id for n in [sidebar_node, header_node] if n}
        content_nodes = [c for c in visible if c.id not in excluded]
        return specs, sidebar_node, content_nodes

    # ------------------------------------------------------------------
    # 2. Repeated pattern detection
    # ------------------------------------------------------------------

    def _find_repeated_patterns(self, children: List["FigmaNode"]) -> List[RepeatedPattern]:
        """Find groups of 3+ siblings with similar dimensions (±10%)."""
        if len(children) < self._MIN_PATTERN_SIZE:
            return []

        sized = [c for c in children if c.width > 0 and c.height > 0]
        used: set = set()
        patterns: List[RepeatedPattern] = []

        for i, pivot in enumerate(sized):
            if pivot.id in used:
                continue
            group = [pivot]
            for j, other in enumerate(sized):
                if j == i or other.id in used:
                    continue
                if (self._similar_dim(pivot.width, other.width, self._DIM_TOLERANCE) and
                        self._similar_dim(pivot.height, other.height, self._DIM_TOLERANCE)):
                    group.append(other)

            if len(group) >= self._MIN_PATTERN_SIZE:
                template = group[0]
                per_instance = [self._extract_instance_data(template, inst) for inst in group]
                patterns.append(RepeatedPattern(
                    template=template,
                    instances=group,
                    per_instance_data=per_instance,
                ))
                for node in group:
                    used.add(node.id)
                logger.info(
                    f"[Decomposer] Repeated pattern: '{template.name}' "
                    f"×{len(group)} ({int(template.width)}×{int(template.height)}px)"
                )

        return patterns

    # ------------------------------------------------------------------
    # 3. Instance data extraction
    # ------------------------------------------------------------------

    def _extract_instance_data(self, template: "FigmaNode", instance: "FigmaNode") -> Dict:
        data: Dict = {}
        self._diff_nodes(template, instance, data, path="")
        return data

    def _diff_nodes(self, t: "FigmaNode", i: "FigmaNode", data: Dict, path: str) -> None:
        if t.type == "TEXT" and i.type == "TEXT" and t.characters != i.characters:
            data[self._make_key(path or t.name, "text")] = i.characters
        t_img = self._get_image_fill_ref(t)
        i_img = self._get_image_fill_ref(i)
        if i_img and i_img != t_img:
            data[self._make_key(path or t.name, "image")] = i_img
        for tc, ic in zip(t.children, i.children):
            self._diff_nodes(tc, ic, data, f"{path}/{tc.name}" if path else tc.name)

    @staticmethod
    def _get_image_fill_ref(node: "FigmaNode") -> Optional[str]:
        for f in node.fills:
            if isinstance(f, dict) and f.get("type") == "IMAGE" and f.get("visible", True):
                ref = f.get("imageRef") or f.get("url") or f.get("imageHash")
                if ref:
                    return str(ref)
        return None

    @staticmethod
    def _make_key(path: str, suffix: str) -> str:
        parts = path.replace("/", "_").replace(" ", "_").split("_")
        camel = parts[0].lower() + "".join(p.capitalize() for p in parts[1:])
        return f"{camel}_{suffix}" if suffix not in camel else camel

    # ------------------------------------------------------------------
    # 4. Section detection
    # ------------------------------------------------------------------

    @staticmethod
    def _is_self_contained_section(node: "FigmaNode") -> bool:
        if node.type not in ("FRAME", "GROUP", "COMPONENT", "INSTANCE"):
            return False
        if node.has_auto_layout:
            return True
        visible = [c for c in node.children if c.visible]
        return len(visible) >= 2 and node.width > 80 and node.height > 40

    # ------------------------------------------------------------------
    # 5. Leaf component detection
    # ------------------------------------------------------------------

    def _find_leaf_components(self, root: "FigmaNode", seen_ids: set) -> List[ComponentSpec]:
        specs: List[ComponentSpec] = []
        if self._classifier is None:
            return specs

        def _walk(node: "FigmaNode") -> None:
            if node.id in seen_ids:
                return
            semantic = self._classifier.classify(node)
            if semantic != "Generic":
                specs.append(self._node_to_spec(node, "leaf", role=semantic))
                seen_ids.add(node.id)
                return  # don't descend — children belong to this component
            for child in node.children:
                _walk(child)

        for child in root.children:
            _walk(child)
        return specs

    # ------------------------------------------------------------------
    # 6. Deduplication
    # ------------------------------------------------------------------

    def _deduplicate_specs(self, specs: List[ComponentSpec]) -> List[ComponentSpec]:
        """
        Group specs by name. For same-named specs:
        - Similar dimensions (±15%): merge into a single template.
        - Different dimensions: append numeric suffix (Name2, Name3, …).
        Preserves original ordering.
        """
        groups: Dict[str, List[ComponentSpec]] = defaultdict(list)
        for s in specs:
            groups[s.name].append(s)

        # Map spec id → final spec (may be mutated)
        final_ids: Dict[int, ComponentSpec] = {}
        for name, group in groups.items():
            if len(group) == 1:
                final_ids[id(group[0])] = group[0]
                continue

            ref = group[0]
            similar = all(
                self._similar_dim(ref.node.width, s.node.width, self._DUP_TOLERANCE) and
                self._similar_dim(ref.node.height, s.node.height, self._DUP_TOLERANCE)
                for s in group[1:]
            )

            if similar:
                # Merge duplicates into template
                all_instances: List[Dict] = list(ref.instances)
                for dup in group[1:]:
                    all_instances.extend(dup.instances if dup.instances else [{}])
                ref.is_template = True
                ref.instance_count = len(group)
                ref.instances = all_instances
                final_ids[id(ref)] = ref
                logger.info(
                    f"[Decomposer] Merged {len(group)} '{name}' (similar dims) → template ×{len(group)}"
                )
            else:
                # Different sizes → keep all with numeric suffixes
                final_ids[id(ref)] = ref  # first keeps original name
                for suffix_i, dup in enumerate(group[1:], start=2):
                    dup.name = f"{name}{suffix_i}"
                    final_ids[id(dup)] = dup
                logger.info(
                    f"[Decomposer] Renamed {len(group)} '{name}' duplicates with suffixes"
                )

        # Restore original order, skipping specs that were merged away
        return [final_ids[id(s)] for s in specs if id(s) in final_ids]

    # ------------------------------------------------------------------
    # Naming helpers
    # ------------------------------------------------------------------

    def _generate_component_name(self, node: "FigmaNode", role: str = None) -> str:
        """
        Return a semantic PascalCase component name for *node*.

        Priority:
          1. Non-auto-generated Figma name → sanitize to PascalCase
          2. Role hint (sidebar / header / footer / nav)
          3. First TEXT child content → "XxxSection"
          4. Position within frame (top bar, side panel)
          5. "Section{N}" fallback
        """
        raw = (node.name or "").strip()

        # 1. Use the Figma name if it's meaningful (not auto-generated)
        if raw and not _AUTO_GENERATED_RE.match(raw):
            pascal = _to_pascal(raw)
            if pascal and len(pascal) >= 2:
                return pascal

        # 2. Role-based name
        if role:
            role_l = role.lower()
            role_map = {
                "sidebar": "Sidebar",
                "header": "Header",
                "footer": "Footer",
                "nav": "NavBar",
                "button": "Button",
                "badge": "Badge",
                "card": "Card",
                "avatar": "Avatar",
                "modal": "Modal",
                "toggle": "Toggle",
                "input": "Input",
                "navitem": "NavItem",
            }
            for kw, name in role_map.items():
                if kw in role_l:
                    return name

        # 3. First TEXT child → "XxxSection"
        text = _first_text_content(node)
        if text:
            words = re.split(r'\s+', text.strip())[:2]
            pascal = "".join(w.capitalize() for w in words if re.match(r'[A-Za-z]', w))
            if pascal and len(pascal) >= 3:
                return pascal + "Section"

        # 4. Position-based fallback
        if node.absolute_bounds and self._frame_w > 1:
            nx = node.absolute_bounds.get("x", 0) - self._frame_x
            ny = node.absolute_bounds.get("y", 0) - self._frame_y
            w, h = node.width, node.height
            # Left side, narrow, tall → SidePanel
            if nx < self._frame_w * 0.05 and w < self._frame_w * 0.32 and h > self._frame_h * 0.30:
                return "SidePanel"
            # Near top, wide, short → TopBar
            if ny < self._frame_h * 0.15 and w > self._frame_w * 0.70 and h < self._frame_h * 0.15:
                return "TopBar"

        # 5. Section counter fallback
        self._section_counter += 1
        return f"Section{self._section_counter}"

    # ------------------------------------------------------------------
    # Spec factory helpers
    # ------------------------------------------------------------------

    def _pattern_to_spec(self, pat: RepeatedPattern) -> ComponentSpec:
        name = self._generate_component_name(pat.template)
        cols, gap = self._compute_grid_dims(pat)
        return ComponentSpec(
            name=name,
            node=pat.template,
            component_type="repeated_pattern",
            crop_box=self._crop_box(pat.template),
            is_template=True,
            instances=pat.per_instance_data,
            instance_count=len(pat.instances),
            cols_per_row=cols,
            gap_px=gap,
        )

    def _compute_grid_dims(self, pat: RepeatedPattern) -> Tuple[int, int]:
        """
        Derive (cols_per_row, gap_px) from the actual positions of repeated instances.

        Strategy:
          1. Group instances by their y-coordinate (bucket width = child height * 0.3).
             The largest bucket = number of columns per row.
          2. Within the top row, sort by x and compute the average inter-item gap.
        Returns (0, 0) if absolute_bounds are unavailable.
        """
        instances = pat.instances
        child_w = pat.template.width
        child_h = pat.template.height

        # Collect (x, y) for each instance that has absolute_bounds
        positions = []
        for node in instances:
            if node.absolute_bounds:
                positions.append((
                    node.absolute_bounds.get("x", 0),
                    node.absolute_bounds.get("y", 0),
                ))

        if not positions or child_w <= 0:
            return (0, 0)

        # Group by y-row: two items are in the same row if their y-coords are within
        # 30% of child_h of each other.
        bucket_size = max(1.0, child_h * 0.3)
        rows: Dict[int, List[float]] = defaultdict(list)
        for x, y in positions:
            bucket = int(y / bucket_size)
            rows[bucket].append(x)

        # cols = size of the largest y-bucket (most items in one row)
        cols = max(len(xs) for xs in rows.values())
        cols = max(1, cols)

        # gap = average x-spacing between items in the top (first) row
        top_bucket = min(rows.keys())
        top_xs = sorted(rows[top_bucket])
        if len(top_xs) >= 2:
            gaps = [top_xs[i + 1] - top_xs[i] - child_w for i in range(len(top_xs) - 1)]
            gap = max(0, round(sum(gaps) / len(gaps)))
        else:
            gap = 0

        logger.info(
            f"[Decomposer] Grid dims for '{pat.template.name}': "
            f"cols={cols}, gap={gap}px (child={int(child_w)}×{int(child_h)}px, "
            f"{len(instances)} instances)"
        )
        return (cols, gap)

    def _node_to_spec(
        self,
        node: "FigmaNode",
        component_type: str,
        name: Optional[str] = None,
        role: Optional[str] = None,
    ) -> ComponentSpec:
        if name is None:
            name = self._generate_component_name(node, role)
        return ComponentSpec(
            name=name,
            node=node,
            component_type=component_type,
            crop_box=self._crop_box(node),
            is_template=False,
            instances=[],
            instance_count=1,
        )

    def _crop_box(self, node: "FigmaNode") -> Tuple[int, int, int, int]:
        """(x, y, w, h) relative to the frame's top-left corner."""
        if not node.absolute_bounds:
            return (0, 0, max(1, int(node.width)), max(1, int(node.height)))
        x = max(0, int(node.absolute_bounds.get("x", 0) - self._frame_x))
        y = max(0, int(node.absolute_bounds.get("y", 0) - self._frame_y))
        return (x, y, max(1, int(node.width)), max(1, int(node.height)))

    @staticmethod
    def _similar_dim(a: float, b: float, tol: float) -> bool:
        if a == 0 or b == 0:
            return False
        return abs(a - b) / max(a, b) <= tol


# ---------------------------------------------------------------------------
# Module-level helpers (no self needed)
# ---------------------------------------------------------------------------

def _to_pascal(name: str) -> str:
    """
    Convert any Figma layer name to a valid PascalCase JS identifier.
    'story card' → 'StoryCard', 'nav-bar' → 'NavBar', 'Welcome, Back!' → 'WelcomeBack'
    Strips all non-alphanumeric characters before splitting.
    """
    # Replace every non-alphanumeric char (commas, dots, parens, etc.) with a space
    cleaned = re.sub(r"[^a-zA-Z0-9]", " ", name)
    parts = cleaned.split()
    pascal = "".join(p.capitalize() for p in parts if p)
    pascal = re.sub(r"^\d+", "", pascal)  # strip leading digits — invalid JS identifier start
    return pascal


def _first_text_content(node: "FigmaNode") -> Optional[str]:
    """Return the characters of the first TEXT descendant, or None."""
    if node.type == "TEXT" and node.characters:
        return node.characters.strip()
    for child in node.children:
        result = _first_text_content(child)
        if result:
            return result
    return None
