#!/usr/bin/env python3
"""Deterministic checks for same-camera coordinate and color evidence."""

from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import coordinate_color_compare as color_test
import occlusion_mask_test as mask_test


class CoordinateColorTests(unittest.TestCase):
    def fixture(self, root: Path, count: int = 8, changed_color: bool = False, admit_layers: bool = True) -> tuple[Path, Path, Path, Path]:
        refs, renders = root / "refs", root / "renders"
        refs.mkdir()
        renders.mkdir()
        views, alignments, render_rows = [], [], []
        for index in range(count):
            view_id = f"view-{index:03d}"
            reference = Image.new("RGBA", (64, 96), (0, 0, 0, 0))
            ImageDraw.Draw(reference).ellipse((16, 8, 48, 88), fill=(210, 90, 50, 255))
            ref_path = refs / f"{view_id}.png"
            reference.save(ref_path)
            model = reference.copy()
            if changed_color and index == 2:
                ImageDraw.Draw(model).ellipse((16, 8, 48, 88), fill=(40, 140, 230, 255))
            model_path = renders / f"{view_id}.png"
            model.save(model_path)
            views.append({"view_id": view_id, "target_yaw_deg": index * 360.0 / count, "path": f"refs/{view_id}.png", "sha256": color_test.sha256(ref_path), "width": 64, "height": 96})
            alignments.append({"view_id": view_id, "subject_bbox_px": [16, 8, 49, 89]})
            render_rows.append({"view_id": view_id, "path": str(model_path), "sha256": color_test.sha256(model_path), "width": 64, "height": 96})
        reference_path = root / "reference-set.json"
        reference_path.write_text(json.dumps({"schema": mask_test.REFERENCE_SCHEMA, "views": views}), encoding="utf-8")
        alignment_path = root / "alignment.json"
        alignment_path.write_text(json.dumps({"schema": mask_test.ALIGNMENT_SCHEMA, "reference_set_sha256": color_test.sha256(reference_path), "views": alignments}), encoding="utf-8")
        render_path = root / "render-report.json"
        render_path.write_text(json.dumps({"schema": mask_test.RENDER_SCHEMA, "reference_set_sha256": color_test.sha256(reference_path), "alignment_sha256": color_test.sha256(alignment_path), "resolution_percentage": 100, "renders": render_rows}), encoding="utf-8")
        masks_out = root / "reference-masks"
        mask_test.command_masks(argparse.Namespace(reference_set=str(reference_path), out=str(masks_out), mode="alpha", mask_dir=None, threshold=16))
        mask_manifest_path = masks_out / "reference-masks.json"
        mask_manifest = json.loads(mask_manifest_path.read_text(encoding="utf-8"))
        mask_manifest["status"] = "pass"
        mask_manifest["reviewer"] = "unit test"
        mask_manifest["reviewed_at"] = "2026-09-08T00:00:00Z"
        mask_manifest["all_masks_visual_match"]["status"] = "pass"
        for row in mask_manifest["views"]:
            row["visual_status"] = "pass"
        mask_manifest_path.write_text(json.dumps(mask_manifest), encoding="utf-8")
        layers_out = root / "mask-layers"
        mask_test.command_compare(argparse.Namespace(reference_set=str(reference_path), alignment=str(alignment_path), render_report=str(render_path), reference_masks=str(mask_manifest_path), out=str(layers_out), model_alpha_threshold=8))
        layer_path = layers_out / "mask-layer-comparison.json"
        layer_report = json.loads(layer_path.read_text(encoding="utf-8"))
        if admit_layers:
            for row in layer_report["views"]:
                row["agent_review"]["status"] = "pass"
        layer_path.write_text(json.dumps(layer_report), encoding="utf-8")
        return reference_path, alignment_path, render_path, layer_path

    def compare(self, root: Path, count: int = 8, changed_color: bool = False, admit_layers: bool = True) -> tuple[dict, Path]:
        reference, alignment, render, layers = self.fixture(root, count, changed_color, admit_layers)
        output = root / "coordinate-color"
        result = color_test.command_compare(argparse.Namespace(reference_set=str(reference), alignment=str(alignment), render_report=str(render), mask_layer_report=str(layers), out=str(output), checker_size=16))
        self.assertEqual(result, 0)
        report_path = output / "fused-multiview-comparison.json"
        return json.loads(report_path.read_text(encoding="utf-8")), report_path

    def test_identical_colors_create_black_difference(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report, report_path = self.compare(Path(temp_dir))
            diff_path = Path(report["views"][0]["evidence"]["color_difference"]["path"])
            with Image.open(diff_path) as image:
                self.assertEqual(int(np.asarray(image).max()), 0)
            self.assertEqual(color_test.validate_comparison_report(report_path)["status"], "pass")

    def test_changed_color_remains_visual_evidence_not_score(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report, report_path = self.compare(Path(temp_dir), changed_color=True)
            target = next(row for row in report["views"] if row["view_id"] == "view-002")
            diff_path = Path(target["evidence"]["color_difference"]["path"])
            with Image.open(diff_path) as image:
                self.assertGreater(int(np.asarray(image).max()), 0)
            self.assertEqual(target["agent_review"]["status"], "pending")
            self.assertNotIn("metrics", target)
            self.assertEqual(color_test.validate_comparison_report(report_path)["status"], "pass")

    def test_pending_mask_review_is_fused_instead_of_blocking_color(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reference, alignment, render, layers = self.fixture(root, admit_layers=False)
            output = root / "fused"
            self.assertEqual(color_test.command_compare(argparse.Namespace(reference_set=str(reference), alignment=str(alignment), render_report=str(render), mask_layer_report=str(layers), out=str(output), checker_size=16)), 0)
            report = json.loads((output / "fused-multiview-comparison.json").read_text(encoding="utf-8"))
            review = report["views"][0]["agent_review"]
            self.assertEqual(review["mask_scale"]["status"], "pending")
            self.assertEqual(review["coordinate_color"]["status"], "pending")

    def test_fused_panel_contains_mask_and_color_for_one_angle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report, _ = self.compare(Path(temp_dir))
            panel_path = Path(report["views"][0]["evidence"]["fused_mask_scale_color_panel"]["path"])
            with Image.open(panel_path) as panel:
                self.assertEqual(panel.size, (64 * 6, 96))

    def test_overall_pass_requires_both_subgates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report, report_path = self.compare(Path(temp_dir))
            report["views"][0]["agent_review"]["status"] = "pass"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            result = color_test.validate_comparison_report(report_path)
            self.assertEqual(result["status"], "fail")
            self.assertTrue(any("both fused sub-gates" in error for error in result["errors"]))

    def test_coordinate_color_evidence_scales_to_72_angles(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
