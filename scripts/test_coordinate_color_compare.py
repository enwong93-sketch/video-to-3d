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
        report_path = output / "coordinate-color-comparison.json"
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
            target = report["views"][2]
            diff_path = Path(target["evidence"]["color_difference"]["path"])
            with Image.open(diff_path) as image:
                self.assertGreater(int(np.asarray(image).max()), 0)
            self.assertEqual(target["agent_review"]["status"], "pending")
            self.assertNotIn("metrics", target)
            self.assertEqual(color_test.validate_comparison_report(report_path)["status"], "pass")

    def test_step_five_review_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reference, alignment, render, layers = self.fixture(root, admit_layers=False)
            with self.assertRaises(color_test.ColorCompareError):
                color_test.command_compare(argparse.Namespace(reference_set=str(reference), alignment=str(alignment), render_report=str(render), mask_layer_report=str(layers), out=str(root / "blocked"), checker_size=16))
            self.assertFalse((root / "blocked").exists())

    def test_coordinate_color_evidence_scales_to_72_angles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report, _ = self.compare(Path(temp_dir), count=72)
            self.assertEqual(report["view_count"], 72)


if __name__ == "__main__":
    unittest.main()
