#!/usr/bin/env python3
"""Deterministic checks for simple same-coordinate mask layering."""

from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import occlusion_mask_test as mask_test


class MaskLayerTests(unittest.TestCase):
    def make_fixture(self, root: Path, count: int = 8, changed_view: bool = False) -> tuple[Path, Path, Path, Path]:
        refs, renders = root / "refs", root / "renders"
        refs.mkdir()
        renders.mkdir()
        views, alignment_views, render_rows = [], [], []
        for index in range(count):
            view_id = f"view-{index:03d}"
            reference = Image.new("RGBA", (64, 96), (0, 0, 0, 0))
            ImageDraw.Draw(reference).rectangle((18, 10, 46, 86), fill=(255, 180, 100, 255))
            reference_path = refs / f"{view_id}.png"
            reference.save(reference_path)
            model = reference.copy()
            if changed_view and index == 2:
                draw = ImageDraw.Draw(model)
                draw.rectangle((18, 48, 28, 86), fill=(0, 0, 0, 0))
                draw.rectangle((47, 20, 54, 42), fill=(100, 220, 255, 255))
            model_path = renders / f"{view_id}.png"
            model.save(model_path)
            views.append({"view_id": view_id, "target_yaw_deg": index * 360.0 / count, "path": f"refs/{view_id}.png", "sha256": mask_test.sha256(reference_path), "width": 64, "height": 96})
            alignment_views.append({"view_id": view_id, "subject_bbox_px": [18, 10, 47, 87]})
            render_rows.append({"view_id": view_id, "path": str(model_path), "sha256": mask_test.sha256(model_path), "width": 64, "height": 96})
        reference_path = root / "reference-set.json"
        reference_path.write_text(json.dumps({"schema": mask_test.REFERENCE_SCHEMA, "views": views}), encoding="utf-8")
        alignment_path = root / "alignment.json"
        alignment_path.write_text(json.dumps({"schema": mask_test.ALIGNMENT_SCHEMA, "reference_set_sha256": mask_test.sha256(reference_path), "views": alignment_views}), encoding="utf-8")
        render_path = root / "render-report.json"
        render_path.write_text(json.dumps({"schema": mask_test.RENDER_SCHEMA, "reference_set_sha256": mask_test.sha256(reference_path), "alignment_sha256": mask_test.sha256(alignment_path), "resolution_percentage": 100, "renders": render_rows}), encoding="utf-8")
        masks_dir = root / "reference-masks"
        self.assertEqual(mask_test.command_masks(argparse.Namespace(reference_set=str(reference_path), out=str(masks_dir), mode="alpha", mask_dir=None, threshold=16)), 0)
        manifest_path = masks_dir / "reference-masks.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["status"] = "pass"
        manifest["reviewer"] = "unit test"
        manifest["reviewed_at"] = "2026-09-07T00:00:00Z"
        manifest["all_masks_visual_match"]["status"] = "pass"
        for row in manifest["views"]:
            row["visual_status"] = "pass"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return reference_path, alignment_path, render_path, manifest_path

    def compare(self, root: Path, count: int = 8, changed_view: bool = False) -> tuple[dict, Path]:
        reference, alignment, render, masks = self.make_fixture(root, count, changed_view)
        output = root / "comparison"
        result = mask_test.command_compare(
            argparse.Namespace(
                reference_set=str(reference),
                alignment=str(alignment),
                render_report=str(render),
                reference_masks=str(masks),
                out=str(output),
                model_alpha_threshold=8,
            )
        )
        self.assertEqual(result, 0)
        report_path = output / "mask-layer-comparison.json"
        return json.loads(report_path.read_text(encoding="utf-8")), report_path

    def test_identical_layers_show_only_green_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report, report_path = self.compare(Path(temp_dir))
            self.assertEqual(report["status"], "needs-agent-review")
            overlay_path = Path(report["views"][0]["evidence"]["mask_layer_overlay"]["path"])
            colors = np.asarray(Image.open(overlay_path).convert("RGB"))
            self.assertTrue(np.any(np.all(colors == (40, 220, 90), axis=2)))
            self.assertFalse(np.any(np.all(colors == (245, 65, 65), axis=2)))
            self.assertFalse(np.any(np.all(colors == (55, 125, 245), axis=2)))
            self.assertEqual(mask_test.validate_comparison_report(report_path)["status"], "pass")

    def test_changed_layer_shows_reference_only_and_model_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report, report_path = self.compare(Path(temp_dir), changed_view=True)
            target = next(row for row in report["views"] if row["view_id"] == "view-002")
            overlay_path = Path(target["evidence"]["mask_layer_overlay"]["path"])
            colors = np.asarray(Image.open(overlay_path).convert("RGB"))
            self.assertTrue(np.any(np.all(colors == (245, 65, 65), axis=2)))
            self.assertTrue(np.any(np.all(colors == (55, 125, 245), axis=2)))
            self.assertEqual(target["agent_review"]["status"], "pending")
            self.assertNotIn("repair_targets", target)
            self.assertNotIn("metrics", target)
            self.assertEqual(mask_test.validate_comparison_report(report_path)["status"], "pass")

    def test_simple_layering_scales_to_72_angles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report, _ = self.compare(Path(temp_dir), count=72)
            self.assertEqual(report["view_count"], 72)

    def test_eight_angles_follow_quadrant_rounds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report, _ = self.compare(Path(temp_dir))
            self.assertEqual([row["view_id"] for row in report["views"]], [
                "view-000", "view-002", "view-004", "view-006",
                "view-001", "view-003", "view-005", "view-007",
            ])

    def test_changed_evidence_hash_fails_integrity_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report, report_path = self.compare(Path(temp_dir))
            report["views"][0]["evidence"]["mask_layer_overlay"]["sha256"] = "0" * 64
            report_path.write_text(json.dumps(report), encoding="utf-8")
            self.assertEqual(mask_test.validate_comparison_report(report_path)["status"], "fail")


if __name__ == "__main__":
    unittest.main()
