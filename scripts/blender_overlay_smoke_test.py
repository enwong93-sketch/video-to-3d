#!/usr/bin/env python3
"""Blender-runtime smoke test for the mandatory per-camera reference overlays."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import bpy

from blender_reference_setup import ALIGNMENT_SCHEMA, REFERENCE_SCHEMA, build_scene, sha256, verify_scene
from artifact_safety import quadrant_order_manifest


def main() -> int:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
        root = Path(temp)
        image_path = root / "reference.png"
        image = bpy.data.images.new("V3D_SMOKE_REFERENCE", width=64, height=96, alpha=True)
        image.filepath_raw = str(image_path)
        image.file_format = "PNG"
        image.save()
        image_hash = sha256(image_path)
        views = [
            {
                "view_id": f"view-{index:03d}",
                "target_yaw_deg": index * 15.0,
                "timestamp_seconds": index / 24.0,
                "path": image_path.name,
                "sha256": image_hash,
                "width": 64,
                "height": 96,
            }
            for index in range(24)
        ]
        reference_path = root / "reference-set.json"
        reference_path.write_text(json.dumps({"schema": REFERENCE_SCHEMA, "views": views, "analysis_order": quadrant_order_manifest(views)}), encoding="utf-8")
        alignment_path = root / "alignment.json"
        alignment_path.write_text(
            json.dumps(
                {
                    "schema": ALIGNMENT_SCHEMA,
                    "reference_set_sha256": sha256(reference_path),
                    "target_height_m": 1.7,
                    "target_center_z_m": 0.85,
                    "camera_distance_m": 8.0,
                    "background_alpha": 0.65,
                    "views": [
                        {"view_id": row["view_id"], "subject_bbox_px": [16, 8, 48, 88]}
                        for row in views
                    ],
                }
            ),
            encoding="utf-8",
        )
        blend_path = root / "overlay-smoke.blend"
        built = build_scene(reference_path, alignment_path, blend_path, clear_scene=True)
        verified = verify_scene(reference_path, alignment_path)
        assert built["status"] == "pass"
        assert verified["status"] == "pass", verified["errors"]
        assert built["view_count"] == built["reference_layer_count"] == 24
        assert verified["view_count"] == verified["reference_layer_count"] == 24
        assert [row["view_id"] for row in verified["cameras"]] == [
            "view-000", "view-006", "view-012", "view-018",
            "view-003", "view-009", "view-015", "view-021",
            "view-001", "view-007", "view-013", "view-019",
            "view-004", "view-010", "view-016", "view-022",
            "view-002", "view-008", "view-014", "view-020",
            "view-005", "view-011", "view-017", "view-023",
        ]
        for row in verified["cameras"]:
            layer = row["reference_layer"]
            assert layer["kind"] == "camera_background_image"
            assert layer["display_depth"] == "FRONT"
            assert abs(layer["alpha"] - 0.65) < 1e-6
            assert layer["frame_method"] == "FIT"
            assert layer["non_rendering"] is True
        print(json.dumps({"status": "pass", "views": 24, "reference_layers": 24, "mode": verified["reference_overlay_mode"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
