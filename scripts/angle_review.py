#!/usr/bin/env python3
"""Prepare and verify every-angle scale, proportion, visual-match, and beauty evidence."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw

from artifact_safety import read_json_limited, safe_output_path, validate_image_size, validate_view_ids

from coordinate_color_compare import (
    COMPARE_SCHEMA as COORDINATE_COLOR_SCHEMA,
    ColorCompareError,
    validate_comparison_report as validate_coordinate_color_report,
)
from occlusion_mask_test import (
    COMPARE_SCHEMA as MASK_LAYER_SCHEMA,
    MaskError,
    validate_comparison_report as validate_mask_layer_report,
)


REFERENCE_SCHEMA = "video-to-3d-model/reference-set/v2"
ALIGNMENT_SCHEMA = "video-to-3d-model/alignment/v1"
RENDER_SCHEMA = "video-to-3d-model/render-set/v1"
REVIEW_SCHEMA = "video-to-3d-model/every-angle-review/v4"
REPORT_SCHEMA = "video-to-3d-model/every-angle-verification/v4"
GATES = (
    "mask_layer_match",
    "coordinate_color_match",
    "silhouette_match",
    "proportion_match",
    "scale_match",
    "visual_match",
    "beauty",
)


class ReviewError(RuntimeError):
    pass


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return read_json_limited(path, error_type=ReviewError)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def alpha_bbox(image: Image.Image) -> tuple[int, int, int, int]:
    rgba = image.convert("RGBA")
    bbox = rgba.getchannel("A").point(lambda value: 255 if value >= 8 else 0).getbbox()
    if bbox is None:
        raise ReviewError("model render has no non-transparent pixels")
    return tuple(int(value) for value in bbox)


def relative_error(actual: float, target: float) -> float:
    return abs(actual - target) / target * 100.0 if target else math.inf


def scale_bbox(bbox: list[float], factor: float) -> tuple[float, float, float, float]:
    return tuple(float(value) * factor for value in bbox)


def prepare(args: argparse.Namespace) -> int:
    reference_path = Path(args.reference_set).expanduser().resolve()
    alignment_path = Path(args.alignment).expanduser().resolve()
    render_path = Path(args.render_report).expanduser().resolve()
    mask_layer_path = Path(args.mask_layer_report).expanduser().resolve()
    coordinate_color_path = Path(args.coordinate_color_report).expanduser().resolve()
    output = Path(args.out).expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise ReviewError(f"review output directory is not empty: {output}")
    reference, alignment, render, mask_layers, coordinate_color = (
        read_json(reference_path),
        read_json(alignment_path),
        read_json(render_path),
        read_json(mask_layer_path),
        read_json(coordinate_color_path),
    )
    if reference.get("schema") != REFERENCE_SCHEMA or alignment.get("schema") != ALIGNMENT_SCHEMA or render.get("schema") != RENDER_SCHEMA:
        raise ReviewError("unsupported reference, alignment, or render schema")
    if alignment.get("reference_set_sha256") != sha256(reference_path):
        raise ReviewError("alignment does not match the reference-set hash")
    if render.get("reference_set_sha256") != sha256(reference_path):
        raise ReviewError("render report does not match the reference-set hash")
    if render.get("alignment_sha256") != sha256(alignment_path):
        raise ReviewError("render report does not match the alignment hash")
    mask_layer_verification = validate_mask_layer_report(mask_layer_path)
    if mask_layers.get("schema") != MASK_LAYER_SCHEMA or mask_layer_verification["status"] != "pass":
        raise ReviewError("every-angle mask-layer evidence is invalid: " + "; ".join(mask_layer_verification["errors"]))
    if mask_layers.get("reference_set_sha256") != sha256(reference_path) or mask_layers.get("alignment_sha256") != sha256(alignment_path) or mask_layers.get("render_report_sha256") != sha256(render_path):
        raise ReviewError("mask-layer report does not match the current reference, alignment, and renders")
    color_verification = validate_coordinate_color_report(coordinate_color_path)
    if coordinate_color.get("schema") != COORDINATE_COLOR_SCHEMA or color_verification["status"] != "pass":
        raise ReviewError("every-angle coordinate/color evidence is invalid: " + "; ".join(color_verification["errors"]))
    if coordinate_color.get("reference_set_sha256") != sha256(reference_path) or coordinate_color.get("alignment_sha256") != sha256(alignment_path) or coordinate_color.get("render_report_sha256") != sha256(render_path) or coordinate_color.get("mask_layer_report_sha256") != sha256(mask_layer_path):
        raise ReviewError("coordinate/color report does not match the current reference, alignment, renders, and mask layers")
    validate_view_ids(reference.get("views") or [], error_type=ReviewError)
    views = {row["view_id"]: row for row in reference.get("views") or []}
    alignments = {row["view_id"]: row for row in alignment.get("views") or []}
    renders = {row["view_id"]: row for row in render.get("renders") or []}
    mask_layer_rows = {row["view_id"]: row for row in mask_layers.get("views") or []}
    color_rows = {row["view_id"]: row for row in coordinate_color.get("views") or []}
    if not 8 <= len(views) <= 72 or set(views) != set(alignments) or set(views) != set(renders) or set(views) != set(mask_layer_rows) or set(views) != set(color_rows):
        raise ReviewError("reference, alignment, render, mask-layer, and coordinate/color reports must contain the same 8-72 view IDs")
    incomplete_layers = [view_id for view_id, row in mask_layer_rows.items() if (row.get("agent_review") or {}).get("status") != "pass"]
    incomplete_colors = [view_id for view_id, row in color_rows.items() if (row.get("agent_review") or {}).get("status") != "pass"]
    if incomplete_layers:
        raise ReviewError("Step 5 mask-layer Agent review is incomplete: " + ", ".join(sorted(incomplete_layers)))
    if incomplete_colors:
        raise ReviewError("Step 6 coordinate/color Agent review is incomplete: " + ", ".join(sorted(incomplete_colors)))
    output.mkdir(parents=True, exist_ok=True)
    evidence_dir = output / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    factor = float(render.get("resolution_percentage", 100)) / 100.0
    rows = []
    for view_id in sorted(views, key=lambda key: float(views[key]["target_yaw_deg"])):
        ref_file = (reference_path.parent / views[view_id]["path"]).resolve()
        model_file = Path(renders[view_id]["path"]).expanduser().resolve()
        if not ref_file.is_file() or sha256(ref_file) != views[view_id].get("sha256"):
            raise ReviewError(f"{view_id} reference image is missing or changed")
        if not model_file.is_file() or sha256(model_file) != renders[view_id].get("sha256"):
            raise ReviewError(f"{view_id} render is missing or changed")
        ref = Image.open(ref_file).convert("RGBA")
        model = Image.open(model_file).convert("RGBA")
        expected_size = (round(ref.width * factor), round(ref.height * factor))
        if model.size != expected_size:
            raise ReviewError(f"{view_id} render size {model.size} does not match expected {expected_size}")
        ref_scaled = ref.resize(model.size, Image.Resampling.LANCZOS) if factor != 1.0 else ref
        reference_bbox = scale_bbox(alignments[view_id]["subject_bbox_px"], factor)
        model_bbox = alpha_bbox(model)
        ref_w, ref_h = reference_bbox[2] - reference_bbox[0], reference_bbox[3] - reference_bbox[1]
        model_w, model_h = model_bbox[2] - model_bbox[0], model_bbox[3] - model_bbox[1]
        ref_center = ((reference_bbox[0] + reference_bbox[2]) / 2, (reference_bbox[1] + reference_bbox[3]) / 2)
        model_center = ((model_bbox[0] + model_bbox[2]) / 2, (model_bbox[1] + model_bbox[3]) / 2)
        center_error_pct = math.hypot(model_center[0] - ref_center[0], model_center[1] - ref_center[1]) / math.hypot(*model.size) * 100.0
        metrics = {
            "height_error_pct": round(relative_error(model_h, ref_h), 6),
            "width_error_pct": round(relative_error(model_w, ref_w), 6),
            "center_error_pct_of_frame_diagonal": round(center_error_pct, 6),
        }
        overlay = Image.blend(ref_scaled, Image.alpha_composite(Image.new("RGBA", model.size, (128, 128, 128, 255)), model), 0.5)
        validate_image_size(*model.size, count=len(views), error_type=ReviewError)
        overlay_path = safe_output_path(evidence_dir, f"{view_id}-overlay.png", error_type=ReviewError)
        overlay.save(overlay_path)
        difference = ImageChops.difference(ref_scaled.convert("RGB"), Image.alpha_composite(Image.new("RGBA", model.size, (128, 128, 128, 255)), model).convert("RGB"))
        difference_path = safe_output_path(evidence_dir, f"{view_id}-difference.png", error_type=ReviewError)
        difference.save(difference_path)
        panel = Image.new("RGB", (model.width * 3, model.height), "#202020")
        panel.paste(ref_scaled.convert("RGB"), (0, 0))
        panel.paste(Image.alpha_composite(Image.new("RGBA", model.size, (128, 128, 128, 255)), model).convert("RGB"), (model.width, 0))
        panel.paste(overlay.convert("RGB"), (model.width * 2, 0))
        draw = ImageDraw.Draw(panel)
        draw.text((12, 12), f"{view_id} | reference / render / overlay", fill="white")
        panel_path = safe_output_path(evidence_dir, f"{view_id}-panel.png", error_type=ReviewError)
        panel.save(panel_path)
        rows.append(
            {
                "view_id": view_id,
                "yaw_deg": float(views[view_id]["target_yaw_deg"]),
                "reference": {"path": str(ref_file), "sha256": sha256(ref_file), "bbox_px": list(reference_bbox)},
                "render": {"path": str(model_file), "sha256": sha256(model_file), "bbox_px": list(model_bbox)},
                "metrics": metrics,
                "mask_layers": {
                    "canvas": mask_layer_rows[view_id]["canvas"],
                    "reference_mask_bbox_px": mask_layer_rows[view_id]["reference_mask_bbox_px"],
                    "model_mask_bbox_px": mask_layer_rows[view_id]["model_mask_bbox_px"],
                    "evidence": mask_layer_rows[view_id]["evidence"],
                },
                "coordinate_color": {
                    "canvas": color_rows[view_id]["canvas"],
                    "background_rgb": color_rows[view_id]["background_rgb"],
                    "evidence": color_rows[view_id]["evidence"],
                },
                "evidence": {
                    "overlay": {"path": str(overlay_path), "sha256": sha256(overlay_path)},
                    "difference": {"path": str(difference_path), "sha256": sha256(difference_path)},
                    "panel": {"path": str(panel_path), "sha256": sha256(panel_path)},
                },
                "gates": {name: {"status": "pending", "notes": ""} for name in GATES},
            }
        )
    review = {
        "schema": REVIEW_SCHEMA,
        "created_at": now_utc(),
        "reviewer": "",
        "reviewed_at": "",
        "reference_set": str(reference_path),
        "reference_set_sha256": sha256(reference_path),
        "alignment": str(alignment_path),
        "alignment_sha256": sha256(alignment_path),
        "render_report": str(render_path),
        "render_report_sha256": sha256(render_path),
        "mask_layer_report": str(mask_layer_path),
        "mask_layer_report_sha256": sha256(mask_layer_path),
        "coordinate_color_report": str(coordinate_color_path),
        "coordinate_color_report_sha256": sha256(coordinate_color_path),
        "thresholds": {
            "max_height_error_pct": args.max_height_error_pct,
            "max_width_error_pct": args.max_width_error_pct,
            "max_center_error_pct": args.max_center_error_pct,
        },
        "instructions": "Inspect the same-canvas mask overlay first, then the same-camera coordinate/color panel, checkerboard, 50/50 overlay and absolute color difference for every view. The tools display evidence only; the Agent judges repairs and independently sets every gate pass or fail before beauty approval.",
        "views": rows,
        "retopology_review": {
            "status": "pending",
            "verdict": "NO-SHIP",
            "wireframe_evidence": [],
            "evidence_views": [row["view_id"] for row in rows],
            "notes": "",
        },
        "aesthetic_qa_review": {
            "status": "pending",
            "verdict": "NO-SHIP",
            "evidence_views": [row["view_id"] for row in rows],
            "evidence_files": [],
            "notes": "",
        },
        "final_beauty_audit": {"status": "pending", "evidence_views": [row["view_id"] for row in rows], "notes": ""},
    }
    review_path = output / "every-angle-review.json"
    write_json(review_path, review)
    print(json.dumps({"status": "needs-every-angle-review", "review": str(review_path), "views": len(rows)}, ensure_ascii=False))
    return 0


def verify(args: argparse.Namespace) -> int:
    path = Path(args.review).expanduser().resolve()
    review = read_json(path)
    errors: list[str] = []
    if review.get("schema") != REVIEW_SCHEMA:
        errors.append(f"unsupported review schema: {review.get('schema')}")
    rows = review.get("views") if isinstance(review.get("views"), list) else []
    if not 8 <= len(rows) <= 72:
        errors.append("review must contain 8-72 views")
    ids = [row.get("view_id") for row in rows if isinstance(row, dict)]
    if len(ids) != len(set(ids)):
        errors.append("review view IDs are not unique")
    mask_layer_path = Path(str(review.get("mask_layer_report", ""))).expanduser().resolve()
    mask_layer_rows: dict[str, dict[str, Any]] = {}
    if not mask_layer_path.is_file() or sha256(mask_layer_path) != review.get("mask_layer_report_sha256"):
        errors.append("mask-layer report is missing or changed")
    else:
        layer_verification = validate_mask_layer_report(mask_layer_path)
        if layer_verification["status"] != "pass":
            errors.append("mask-layer report no longer verifies: " + "; ".join(layer_verification["errors"]))
        layer_report = read_json(mask_layer_path)
        mask_layer_rows = {row["view_id"]: row for row in layer_report.get("views") or [] if isinstance(row, dict)}
        if set(mask_layer_rows) != set(ids):
            errors.append("mask-layer report view IDs do not match the final review")
        incomplete = [view_id for view_id, row in mask_layer_rows.items() if (row.get("agent_review") or {}).get("status") != "pass"]
        if incomplete:
            errors.append("Step 5 mask-layer Agent review is not pass for: " + ", ".join(sorted(incomplete)))
    coordinate_color_path = Path(str(review.get("coordinate_color_report", ""))).expanduser().resolve()
    color_rows: dict[str, dict[str, Any]] = {}
    if not coordinate_color_path.is_file() or sha256(coordinate_color_path) != review.get("coordinate_color_report_sha256"):
        errors.append("coordinate/color report is missing or changed")
    else:
        color_verification = validate_coordinate_color_report(coordinate_color_path)
        if color_verification["status"] != "pass":
            errors.append("coordinate/color report no longer verifies: " + "; ".join(color_verification["errors"]))
        color_report = read_json(coordinate_color_path)
        color_rows = {row["view_id"]: row for row in color_report.get("views") or [] if isinstance(row, dict)}
        if set(color_rows) != set(ids):
            errors.append("coordinate/color report view IDs do not match the final review")
        incomplete = [view_id for view_id, row in color_rows.items() if (row.get("agent_review") or {}).get("status") != "pass"]
        if incomplete:
            errors.append("Step 6 coordinate/color Agent review is not pass for: " + ", ".join(sorted(incomplete)))
    thresholds = review.get("thresholds") if isinstance(review.get("thresholds"), dict) else {}
    for row in rows:
        view_id = row.get("view_id", "unknown")
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        embedded_layers = row.get("mask_layers") if isinstance(row.get("mask_layers"), dict) else {}
        if view_id in mask_layer_rows:
            source_layers = mask_layer_rows[view_id]
            for field in ("canvas", "reference_mask_bbox_px", "model_mask_bbox_px", "evidence"):
                if embedded_layers.get(field) != source_layers.get(field):
                    errors.append(f"{view_id} embedded mask-layer {field} does not match the source report")
        embedded_color = row.get("coordinate_color") if isinstance(row.get("coordinate_color"), dict) else {}
        if view_id in color_rows:
            source_color = color_rows[view_id]
            for field in ("canvas", "background_rgb", "evidence"):
                if embedded_color.get(field) != source_color.get(field):
                    errors.append(f"{view_id} embedded coordinate/color {field} does not match the source report")
        checks = (
            ("height_error_pct", "max_height_error_pct"),
            ("width_error_pct", "max_width_error_pct"),
            ("center_error_pct_of_frame_diagonal", "max_center_error_pct"),
        )
        for metric, threshold in checks:
            try:
                if float(metrics[metric]) > float(thresholds[threshold]) + 1e-9:
                    errors.append(f"{view_id} {metric} exceeds {threshold}")
            except (KeyError, TypeError, ValueError):
                errors.append(f"{view_id} has invalid {metric} or {threshold}")
        for name in GATES:
            if (row.get("gates") or {}).get(name, {}).get("status") != "pass":
                errors.append(f"{view_id} gate {name} is not pass")
        for name, evidence in (row.get("evidence") or {}).items():
            evidence_path = Path(str(evidence.get("path", ""))).expanduser().resolve()
            if not evidence_path.is_file() or sha256(evidence_path) != evidence.get("sha256"):
                errors.append(f"{view_id} {name} evidence is missing or changed")
    final = review.get("final_beauty_audit") if isinstance(review.get("final_beauty_audit"), dict) else {}
    retopology = review.get("retopology_review") if isinstance(review.get("retopology_review"), dict) else {}
    if retopology.get("status") != "pass" or retopology.get("verdict") != "PASS":
        errors.append("retopology review must have status pass and verdict PASS")
    if set(retopology.get("evidence_views") or []) != set(ids):
        errors.append("retopology review must cite every admitted view")
    wireframes = retopology.get("wireframe_evidence") if isinstance(retopology.get("wireframe_evidence"), list) else []
    if not wireframes:
        errors.append("retopology review requires wireframe evidence")
    for evidence in wireframes:
        evidence_path = Path(str(evidence.get("path", ""))).expanduser().resolve() if isinstance(evidence, dict) else Path("")
        if not evidence_path.is_file() or sha256(evidence_path) != evidence.get("sha256"):
            errors.append("retopology wireframe evidence is missing or changed")
    aesthetics = review.get("aesthetic_qa_review") if isinstance(review.get("aesthetic_qa_review"), dict) else {}
    if aesthetics.get("status") != "pass" or aesthetics.get("verdict") not in {"SHIP", "SHIP WITH NOTES"}:
        errors.append("aesthetic QA must pass with SHIP or SHIP WITH NOTES")
    if set(aesthetics.get("evidence_views") or []) != set(ids):
        errors.append("aesthetic QA must cite every admitted view")
    aesthetic_files = aesthetics.get("evidence_files") if isinstance(aesthetics.get("evidence_files"), list) else []
    if not aesthetic_files:
        errors.append("aesthetic QA requires evidence files")
    for evidence in aesthetic_files:
        evidence_path = Path(str(evidence.get("path", ""))).expanduser().resolve() if isinstance(evidence, dict) else Path("")
        if not evidence_path.is_file() or sha256(evidence_path) != evidence.get("sha256"):
            errors.append("aesthetic QA evidence is missing or changed")
    if final.get("status") != "pass":
        errors.append("final beauty audit is not pass")
    if set(final.get("evidence_views") or []) != set(ids):
        errors.append("final beauty audit must cite every admitted view")
    if not review.get("reviewer") or not review.get("reviewed_at"):
        errors.append("reviewer and reviewed_at are required")
    report = {
        "schema": REPORT_SCHEMA,
        "checked_at": now_utc(),
        "status": "pass" if not errors else "fail",
        "review": str(path),
        "review_sha256": sha256(path),
        "view_count": len(rows),
        "errors": errors,
    }
    report_path = Path(args.report).expanduser().resolve() if args.report else path.with_name("every-angle-verification.json")
    write_json(report_path, report)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "pass" else 2


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare", help="Generate overlays, differences, panels, metrics, and a review template")
    prepare_parser.add_argument("--reference-set", required=True)
    prepare_parser.add_argument("--alignment", required=True)
    prepare_parser.add_argument("--render-report", required=True)
    prepare_parser.add_argument("--mask-layer-report", required=True)
    prepare_parser.add_argument("--coordinate-color-report", required=True)
    prepare_parser.add_argument("--out", required=True)
    prepare_parser.add_argument("--max-height-error-pct", type=float, default=1.0)
    prepare_parser.add_argument("--max-width-error-pct", type=float, default=3.0)
    prepare_parser.add_argument("--max-center-error-pct", type=float, default=1.0)
    prepare_parser.set_defaults(func=prepare)
    verify_parser = sub.add_parser("verify", help="Verify numeric thresholds and every visual/beauty gate")
    verify_parser.add_argument("--review", required=True)
    verify_parser.add_argument("--report")
    verify_parser.set_defaults(func=verify)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return int(args.func(args))
    except (ReviewError, ColorCompareError, MaskError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
