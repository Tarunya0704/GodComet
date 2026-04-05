"""
MCP Figma Converter
===================
Drop-in replacement for ProductionFigmaToCode that uses FigmaMCPClient for
the initial design-data fetch instead of direct Figma REST API calls.

Key differences from ProductionFigmaToCode:
  - Design data fetched via figma-developer-mcp (MCP stdio transport)
  - Figma Variables pulled via get_local_variables() → exact token names
  - All code-generation, scaffolding, and image-download logic inherited
    unchanged from ProductionFigmaToCode

Return format is IDENTICAL to ProductionFigmaToCode.convert() so
workflow_executor.py needs zero changes.

Fallback chain:
  MCP data fetch fails → automatic fallback to ProductionFigmaToCode
  (REST API), ensuring conversions always complete.
"""

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from tools.figma_mcp_client import FigmaMCPClient
from tools.production_figma_converter import (
    AICodeGenerator,
    ComponentClassifier,
    ComponentExtractor,
    DesignTokenExtractor,
    FigmaNode,
    ImageDownloader,
    ProductionFigmaToCode,
    PropBasedGenerator,
    ReactCodeGenerator,
)

logger = logging.getLogger(__name__)


class MCPFigmaConverter(ProductionFigmaToCode):
    """
    Figma → React converter that sources design data from the Figma MCP server
    (figma-developer-mcp) rather than direct REST API calls.

    Inherits every scaffolding helper from ProductionFigmaToCode:
      _generate_nextjs_structure, _generate_package_json, _generate_tailwind_config,
      _generate_postcss_config, _generate_next_config, _generate_tsconfig,
      _generate_gitignore, _generate_readme, _write_component_registry,
      _get_frames, _extract_file_id, _sanitize_name, _export_frame_image, …

    Only convert() is overridden; the rest of the pipeline is identical.
    """

    def __init__(self, figma_token: str):
        # Parent __init__ builds all sub-generators and creates self.mcp_client.
        # Reuse it — do NOT create a second FigmaMCPClient here.
        # Creating two clients races over port 3333: both call _port_in_use()
        # before the first process binds, so both try to spawn → EADDRINUSE →
        # the second crashes, then __del__ kills the first → no server running.
        super().__init__(figma_token)

        if self.mcp_client is not None:
            logger.info("✅ MCPFigmaConverter: reusing MCP client from parent (port %d)", self.mcp_client._port)
        else:
            # Parent failed to create a client (Node.js missing, bad token, etc.)
            # Try once more — by now __init__ is done so there's no race.
            try:
                self.mcp_client = FigmaMCPClient(figma_token)
                logger.info("✅ MCPFigmaConverter: MCP client ready (fallback init)")
            except Exception as _e:
                logger.warning(
                    f"MCPFigmaConverter: MCP client unavailable ({_e}). "
                    "Will fall back to REST API on every convert() call."
                )
                self.mcp_client = None

    # ── MCP node → FigmaNode ──────────────────────────────────────────────────

    def _mcp_node_to_figma_node(self, node_dict: Dict) -> FigmaNode:
        """
        Convert an MCP node dict to a FigmaNode.

        figma-developer-mcp returns standard Figma REST API JSON — the same
        shape that _fetch_file() returns — so no property remapping is needed.
        FigmaNode's constructor handles the full mapping from raw API dicts.

        The method exists as an explicit seam so future format differences can
        be handled here without touching the rest of the pipeline.
        """
        return FigmaNode(node_dict)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _normalise_mcp_colors(self, raw: Dict[str, str]) -> Dict[str, str]:
        """
        Normalise Figma Variable path names to Tailwind-safe token keys.
          "Colors/Primary/500"  →  "primary-500"
          "Neutral/Gray/100"    →  "neutral-gray-100"
          "background/default"  →  "background-default"
        """
        out: Dict[str, str] = {}
        for var_name, hex_val in raw.items():
            parts = var_name.lower().split("/")
            if parts and parts[0] in ("colors", "color"):
                parts = parts[1:]
            key = "-".join(p.strip() for p in parts if p.strip())
            if key:
                out[key] = hex_val
        return out

    # ── Main convert() ────────────────────────────────────────────────────────

    async def convert(
        self,
        figma_url: str,
        output_dir: Path,
        figma_screenshot_path: str = None,
    ) -> Dict:
        """
        Convert a Figma design to a production-ready Next.js project.

        Uses FigmaMCPClient for the design-tree fetch and Figma Variables.
        All downstream code-generation steps are identical to
        ProductionFigmaToCode.convert().

        Falls back to ProductionFigmaToCode.convert() (REST API) if:
          - MCP client not available
          - MCP returns empty file data
          - Any unhandled exception in the MCP fetch phase

        Return dict (identical to ProductionFigmaToCode):
          {
            "success": bool,
            "components": [...],
            "images": int,
            "output_dir": str,
            "file_name": str,
            "first_frame_node_id": str | None,
            "thumbnail_url": str | None,
            "registry_path": str,
          }
          OR {"success": False, "error": str}
        """
        if not self.mcp_client:
            logger.warning("MCP client not available — delegating to REST API converter")
            return await super().convert(figma_url, output_dir, figma_screenshot_path)

        try:
            return await self._convert_via_mcp(figma_url, output_dir, figma_screenshot_path)
        except Exception as _e:
            logger.error(
                f"MCP conversion failed ({_e}). "
                "Falling back to REST API converter.",
                exc_info=True,
            )
            return await super().convert(figma_url, output_dir, figma_screenshot_path)

    async def _convert_via_mcp(
        self,
        figma_url: str,
        output_dir: Path,
        figma_screenshot_path: Optional[str],
    ) -> Dict:
        """
        Core MCP conversion pipeline.  Mirrors ProductionFigmaToCode.convert()
        step-for-step, replacing only the Figma file-data fetch with MCP.
        """
        # ── 1. Parse URL ──────────────────────────────────────────────────────
        file_id, target_node_id = self._extract_file_id(figma_url)
        self._target_node_id = target_node_id
        logger.info(
            f"🎨 [MCP] Converting Figma file: {file_id}"
            + (f" (node: {target_node_id})" if target_node_id else "")
        )

        # ── 2. Fetch design tree via MCP ──────────────────────────────────────
        mcp_data = await self.mcp_client.get_design_data(file_id, target_node_id)
        figma_data: Dict = mcp_data.get("file", {})

        # Accept YAML-parsed data: Figma MCP may return {"metadata": ..., "nodes": ...}
        # instead of the REST-style {"document": ...} shape.
        has_document  = bool(figma_data.get("document"))
        has_yaml_shape = bool(figma_data.get("metadata") or figma_data.get("nodes"))
        if not figma_data or (not has_document and not has_yaml_shape):
            raise RuntimeError(
                "MCP returned empty or incomplete file data "
                f"(keys: {list(figma_data.keys()) if figma_data else 'none'})"
            )

        # If YAML shape (no document key), MCP returned an incomplete format that
        # lacks absoluteBoundingBox, fills/imageRef, and characters.
        # Fall back to REST API immediately — it always returns full node data.
        if not has_document and has_yaml_shape:
            logger.warning(
                "⚠️ [MCP] YAML-shaped response detected — missing fills/imageRef/bounding boxes. "
                "Falling back to REST API for complete node data."
            )
            return await super().convert(figma_url, output_dir, figma_screenshot_path)

        logger.info("✅ [MCP] Design tree fetched")

        # ── 3. Build FigmaNode tree ───────────────────────────────────────────
        root: FigmaNode = self._mcp_node_to_figma_node(figma_data["document"])

        # ── 4. Component extraction ───────────────────────────────────────────
        self.component_extractor = ComponentExtractor()  # reset between runs
        self.component_extractor.extract(root)
        logger.info(
            f"✅ Found {len(self.component_extractor.components)} components"
        )

        # ── 5. Semantic classification ────────────────────────────────────────
        classified = self.classifier.classify_tree(root)
        type_counts: Dict[str, int] = {}
        for sem in classified.values():
            type_counts[sem] = type_counts.get(sem, 0) + 1
        logger.info(
            "✅ Component classification: "
            + ", ".join(f"{t}×{n}" for t, n in sorted(type_counts.items()))
            + f" ({len(classified)} total)"
        )

        # ── 6. Design tokens (AST) ────────────────────────────────────────────
        self.token_extractor = DesignTokenExtractor()
        self.token_extractor.extract(root)
        self.token_extractor.write_tokens_file(output_dir)
        logger.info("✅ Design tokens extracted → src/tokens.ts")

        # ── 7. Design tokens (MCP Variables — exact names) ────────────────────
        mcp_colors: Dict[str, str] = {}
        try:
            mcp_vars = await self.mcp_client.get_local_variables(file_id)
            mcp_colors = self._normalise_mcp_colors(mcp_vars.get("colors", {}))
            if mcp_colors:
                logger.info(
                    f"✅ MCP Variables: {len(mcp_colors)} exact color tokens"
                )
            else:
                logger.info("ℹ️ MCP: file has no Figma Variables — using AST tokens")
        except Exception as _e:
            logger.warning(f"MCP variable fetch failed ({_e}) — using AST tokens only")

        _ast_colors: Dict[str, str] = self.token_extractor.build_tokens().get("colors", {})
        _merged_colors: Dict[str, str] = {**_ast_colors, **mcp_colors}

        # ── 8. Frame selection ────────────────────────────────────────────────
        frames: List[FigmaNode] = self._get_frames(root)
        logger.info(f"✅ Found {len(frames)} screens")
        if not frames:
            raise Exception("No frames found in Figma file")

        # ── 9. Output directory structure ─────────────────────────────────────
        output_dir.mkdir(parents=True, exist_ok=True)
        components_dir = output_dir / "src" / "components"
        components_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "public" / "images").mkdir(parents=True, exist_ok=True)

        # ── 10. UI primitives (Button / Card / Badge) ─────────────────────────
        ui_files = self.prop_generator.generate_ui_components(
            classified, root, output_dir
        )
        if ui_files:
            logger.info(
                f"✅ UI components written: {', '.join(Path(p).name for p in ui_files)}"
            )

        # ── 11. Image download ────────────────────────────────────────────────
        all_nodes: List[FigmaNode] = []
        for frame in frames:
            all_nodes.extend(self.code_generator._get_all_nodes(frame))
        image_map = await self.image_downloader.download_images(
            file_id, all_nodes, output_dir
        )
        logger.info(f"✅ Downloaded {len(image_map)} images")

        # ── 12. Thumbnail / screenshot setup ──────────────────────────────────
        import aiohttp  # already in production_figma_converter deps

        _file_thumbnail_path = figma_screenshot_path
        if not _file_thumbnail_path:
            thumbnail_url = figma_data.get("thumbnailUrl")
            if thumbnail_url:
                try:
                    thumb_path = output_dir / "_figma_thumb.png"
                    async with aiohttp.ClientSession() as _s:
                        async with _s.get(
                            thumbnail_url,
                            timeout=aiohttp.ClientTimeout(total=30),
                        ) as _r:
                            if _r.status == 200:
                                thumb_path.write_bytes(await _r.read())
                                _file_thumbnail_path = str(thumb_path)
                                logger.info(
                                    f"File thumbnail ready: {thumb_path.name} "
                                    f"({thumb_path.stat().st_size // 1024}KB)"
                                )
                except Exception as _e:
                    logger.warning(f"Could not fetch file thumbnail: {_e}")

        # ── 13. Code generation (per frame) ───────────────────────────────────
        use_ai = os.getenv("USE_AI", "true").lower() == "true"
        logger.info(
            f"🔧 Code generation mode: {'AI (pixel-perfect)' if use_ai else 'PROGRAMMATIC'}"
        )

        generated: List[Dict] = []
        for frame in frames:
            comp_name = self._sanitize_name(frame.name)
            logger.info(f"🔨 Generating: {comp_name}")

            # Per-frame screenshot for AI
            _ai_screenshot_path = await self._export_frame_image(
                file_id, frame.id, output_dir
            )
            if _ai_screenshot_path:
                logger.info(
                    f"Using per-frame screenshot for AI: "
                    f"{Path(_ai_screenshot_path).name}"
                )
            elif _file_thumbnail_path:
                _ai_screenshot_path = _file_thumbnail_path
                logger.info("Using file thumbnail as fallback for AI")
            else:
                logger.warning("No screenshot available for AI — quality may be reduced")

            # Layout-type detection
            frame_h = frame.height
            frame_w = frame.width or 1
            _is_landing_page = frame_h > frame_w * 1.5

            # Programmatic skeleton
            logger.info(f"⚙️ [PROGRAMMATIC] Generating {comp_name} from Figma structure")
            code = self.code_generator.generate_component(frame, comp_name, image_map)
            logger.info(f"✅ [PROGRAMMATIC] {comp_name} done ({len(code)} chars)")

            # Override landing-page flag if dashboard pattern was detected
            _dashboard_detected = getattr(frame, "_infer_hscreen", False)
            if _dashboard_detected:
                _is_landing_page = False

            logger.info(
                f"[Layout Type] {comp_name}: "
                f"{'landing page' if _is_landing_page else 'dashboard/other'} "
                f"(h={int(frame_h)}px w={int(frame_w)}px, "
                f"dashboard_detected={_dashboard_detected})"
            )

            # AI enhancement / full generation
            if use_ai and self.ai_generator.available:
                if _is_landing_page:
                    logger.info(
                        f"🎨 [AI FULL] Generating landing page {comp_name} from scratch"
                    )
                    ai_code = self.ai_generator.generate_component(
                        frame,
                        comp_name,
                        image_map,
                        figma_screenshot_path=_ai_screenshot_path,
                        layout_type="landing_page",
                    )
                    if ai_code:
                        code = ai_code
                        logger.info(f"✅ [AI FULL] {comp_name} done ({len(code)} chars)")
                    else:
                        logger.warning(
                            f"⚠️ [AI FULL] returned nothing for {comp_name} "
                            "— keeping programmatic output"
                        )
                else:
                    enhanced = self.ai_generator.enhance_component(
                        code,
                        comp_name,
                        _ai_screenshot_path,
                        token_colors=_merged_colors,
                    )
                    if enhanced:
                        code = enhanced
                    else:
                        logger.warning(
                            f"⚠️ [AI ENHANCE] returned nothing for {comp_name} "
                            "— keeping programmatic output"
                        )
            elif use_ai:
                logger.warning(
                    f"⚠️ USE_AI=true but GROQ_API_KEY not set — using programmatic output"
                )

            # Write component file
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

        # ── 14. Next.js scaffolding ───────────────────────────────────────────
        self._generate_nextjs_structure(output_dir, generated)
        self._generate_package_json(output_dir)
        self._generate_tailwind_config(output_dir, _merged_colors)
        self._generate_postcss_config(output_dir)
        self._generate_next_config(output_dir)
        self._generate_tsconfig(output_dir)
        self._generate_gitignore(output_dir)
        self._generate_readme(output_dir, figma_url)

        # ── 15. Component registry ────────────────────────────────────────────
        registry_path = self._write_component_registry(
            output_dir,
            file_id,
            figma_data.get("name", "Untitled"),
            generated,
        )

        logger.info("🎉 [MCP] Conversion complete!")

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
            "thumbnail_url": figma_data.get("thumbnailUrl"),
            "registry_path": str(registry_path),
        }
