#!/usr/bin/env python3
"""Deterministic checks for the every-angle review verifier."""

from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path

import angle_review


class AngleReviewTests(unittest.TestCase):
    def test_complete_eight_view_review_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evidence = root / "evidence.bin"
            evidence.write_bytes(b"verified-evidence")
            evidence_record = {"path": str(evidence), "sha256": angle_review.sha256(evidence)}
            inputs = {}
            for name in ("reference_set", "alignment", "render_report", "reference_masks"):
                source = root / f"{name}.json"
                source.write_text(name, encoding="utf-8")
                inputs[name] = {"path": str(source), "sha256": angle_review.sha256(source)}
            layer_evidence = {"mask_layer_overlay": evidence_record, "mask_layer_overlay_on_reference": evidence_record}
            numeric_edge = {
                "numeric_gate": "pass",
                "silhouette_exact_match": True,
                "xor_pixels": 0,
                "iou": 1.0,
                "bbox_delta_px": [0, 0, 0, 0],
                "edge_error": {"max_abs_px": 0},
            }
            review_indices = [0, 2, 4, 6, 1, 3, 5, 7]
            layer_rows = [
                {
                    "view_id": f"view-{index:03d}",
                    "review_round": review_index // 4 + 1,
                    "review_position": review_index % 4 + 1,
                    "canvas": {"width": 100, "height": 200, "origin": "top-left", "coordinates": "identical"},
                    "reference_mask_bbox_px": [10, 10, 90, 190],
                    "model_mask_bbox_px": [10, 10, 90, 190],
                    "numeric_edge": numeric_edge,
                    "evidence": layer_evidence,
                    "agent_review": {"status": "pass", "notes": "unit fixture"},
                }
                for review_index, index in enumerate(review_indices)
            ]
            layer_report = {
                "schema": angle_review.MASK_LAYER_SCHEMA,
                "status": "needs-agent-review",
                "view_count": 8,
                "views": layer_rows,
                **{name: record["path"] for name, record in inputs.items()},
                **{f"{name}_sha256": record["sha256"] for name, record in inputs.items()},
            }
            layer_path = root / "mask-layers.json"
            layer_path.write_text(json.dumps(layer_report), encoding="utf-8")
            color_evidence = {
                "reference_projection": evidence_record,
                "model_projection": evidence_record,
                "color_overlay_50_50": evidence_record,
                "color_difference": evidence_record,
                "coordinate_checkerboard": evidence_record,
                "fused_mask_scale_color_panel": evidence_record,
            }
            color_rows = [
                {
                    "view_id": f"view-{index:03d}",
                    "review_round": review_index // 4 + 1,
                    "review_position": review_index % 4 + 1,
                    "canvas": {"width": 100, "height": 200, "origin": "top-left", "coordinates": "identical-camera-projection"},
                    "background_rgb": [128, 128, 128],
                    "mask_scale": {
                        "canvas": layer_rows[review_index]["canvas"],
                        "reference_mask_bbox_px": layer_rows[review_index]["reference_mask_bbox_px"],
                        "model_mask_bbox_px": layer_rows[review_index]["model_mask_bbox_px"],
                        "numeric_edge": numeric_edge,
                        "evidence": layer_evidence,
                    },
                    "evidence": color_evidence,
                    "agent_review": {
                        "status": "pass",
                        "mask_scale": {"status": "pass", "notes": "unit fixture"},
                        "coordinate_color": {"status": "pass", "notes": "unit fixture"},
                        "notes": "unit fixture",
                    },
                }
                for review_index, index in enumerate(review_indices)
            ]
            color_report = {
                "schema": angle_review.COORDINATE_COLOR_SCHEMA,
                "status": "needs-agent-review",
                "view_count": 8,
                "views": color_rows,
                "reference_set": inputs["reference_set"]["path"],
                "reference_set_sha256": inputs["reference_set"]["sha256"],
                "alignment": inputs["alignment"]["path"],
                "alignment_sha256": inputs["alignment"]["sha256"],
                "render_report": inputs["render_report"]["path"],
                "render_report_sha256": inputs["render_report"]["sha256"],
                "mask_layer_report": str(layer_path),
                "mask_layer_report_sha256": angle_review.sha256(layer_path),
            }
            color_path = root / "coordinate-color.json"
            color_path.write_text(json.dumps(color_report), encoding="utf-8")
            rows = []
            for review_index, index in enumerate(review_indices):
                rows.append(
                    {
                        "view_id": f"view-{index:03d}",
                        "review_round": review_index // 4 + 1,
                        "review_position": review_index % 4 + 1,
                        "yaw_deg": index * 45.0,
                        "metrics": {
                            "height_error_pct": 0.0,
                            "width_error_pct": 0.0,
                            "center_error_pct_of_frame_diagonal": 0.0,
                        },
                        "mask_layers": {
                            "canvas": layer_rows[review_index]["canvas"],
                            "reference_mask_bbox_px": layer_rows[review_index]["reference_mask_bbox_px"],
                            "model_mask_bbox_px": layer_rows[review_index]["model_mask_bbox_px"],
                            "numeric_edge": numeric_edge,
                            "evidence": layer_evidence,
                        },
                        "coordinate_color": {
                            "canvas": color_rows[review_index]["canvas"],
                            "background_rgb": color_rows[review_index]["background_rgb"],
                            "evidence": color_evidence,
                        },
                        "evidence": {"overlay": evidence_record, "difference": evidence_record, "panel": evidence_record},
                        "gates": {name: {"status": "pass", "notes": "fixture"} for name in angle_review.GATES},
                    }
                )
            review = {
                "schema": angle_review.REVIEW_SCHEMA,
                "reviewer": "unit test",
                "reviewed_at": "2026-09-07T00:00:00Z",
                "thresholds": {
                    "max_height_error_pct": 1.0,
                    "max_width_error_pct": 3.0,
                    "max_center_error_pct": 1.0,
                },
                "mask_layer_report": str(layer_path),
                "mask_layer_report_sha256": angle_review.sha256(layer_path),
                "coordinate_color_report": str(color_path),
                "coordinate_color_report_sha256": angle_review.sha256(color_path),
                "views": rows,
                "retopology_review": {
                    "status": "pass",
                    "verdict": "PASS",
                    "wireframe_evidence": [evidence_record],
                    "evidence_views": [row["view_id"] for row in rows],
                },
                "aesthetic_qa_review": {
                    "status": "pass",
                    "verdict": "SHIP",
                    "evidence_views": [row["view_id"] for row in rows],
                    "evidence_files": [evidence_record],
                },
                "final_beauty_audit": {"status": "pass", "evidence_views": [row["view_id"] for row in rows]},
            }
            path = root / "review.json"
            path.write_text(json.dumps(review), encoding="utf-8")
            result = angle_review.verify(argparse.Namespace(review=str(path), report=str(root / "report.json")))
            self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
