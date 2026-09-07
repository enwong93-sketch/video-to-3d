#!/usr/bin/env python3
"""Project reference and model color layers onto the same camera pixel coordinates for Agent review."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageStat

from occlusion_mask_test import (
    ALIGNMENT_SCHEMA,
    COMPARE_SCHEMA as MASK_LAYER_SCHEMA,
    REFERENCE_SCHEMA,
    RENDER_SCHEMA,
    MaskError,
    resolve_reference_image,
    validate_comparison_report as validate_mask_layers,
    validate_mask_manifest,
)


COMPARE_SCHEMA = "video-to-3d-model/coordinate-color-comparison/v1"
VERIFY_SCHEMA = "video-to-3d-model/coordinate-color-verification/v1"


class ColorCompareError(RuntimeError):
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
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ColorCompareError(f"cannot read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ColorCompareError(f"JSON root must be an object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def ensure_new_directory(path: Path) -> None:
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ColorCompareError(f"output directory is not empty: {path}")
    path.mkdir(parents=True, exist_ok=True)


def corner_background(image: Image.Image) -> tuple[int, int, int]:
    rgb = image.convert("RGB")
    sample = max(4, min(rgb.width, rgb.height) // 50)
    patches = (
        rgb.crop((0, 0, sample, sample)),
        rgb.crop((rgb.width - sample, 0, rgb.width, sample)),
        rgb.crop((0, rgb.height - sample, sample, rgb.height)),
        rgb.crop((rgb.width - sample, rgb.height - sample, rgb.width, rgb.height)),
    )
    medians = [ImageStat.Stat(patch).median for patch in patches]
    return tuple(int(round(float(np.median([row[channel] for row in medians])))) for channel in range(3))


def checkerboard(reference: Image.Image, model: Image.Image, tile_size: int) -> Image.Image:
    width, height = reference.size
    yy, xx = np.indices((height, width))
    choose_reference = ((xx // tile_size) + (yy // tile_size)) % 2 == 0
    mask = Image.fromarray(np.where(choose_reference, 255, 0).astype(np.uint8))
    return Image.composite(reference, model, mask)


def make_panel(reference: Image.Image, model: Image.Image, blend: Image.Image, difference: Image.Image, view_id: str) -> Image.Image:
    images = [reference.convert("RGB"), model.convert("RGB"), blend.convert("RGB"), difference.convert("RGB")]
    labels = ["reference projection", "model projection", "50/50 overlay", "absolute color difference"]
    output = Image.new("RGB", (reference.width * 4, reference.height), "black")
    for index, image in enumerate(images):
        output.paste(image, (index * reference.width, 0))
        draw = ImageDraw.Draw(output)
        draw.rectangle((index * reference.width, 0, (index + 1) * reference.width, 38), fill="black")
        draw.text((index * reference.width + 8, 8), f"{view_id} | {labels[index]}", fill="white")
    return output


def command_compare(args: argparse.Namespace) -> int:
    reference_path = Path(args.reference_set).expanduser().resolve()
    alignment_path = Path(args.alignment).expanduser().resolve()
    render_path = Path(args.render_report).expanduser().resolve()
    mask_layer_path = Path(args.mask_layer_report).expanduser().resolve()
    output = Path(args.out).expanduser().resolve()
    if not 4 <= args.checker_size <= 256:
        raise ColorCompareError("checker-size must be between 4 and 256 pixels")
    reference, alignment, render, mask_layers = (
        read_json(reference_path),
        read_json(alignment_path),
        read_json(render_path),
        read_json(mask_layer_path),
    )
    if reference.get("schema") != REFERENCE_SCHEMA or alignment.get("schema") != ALIGNMENT_SCHEMA or render.get("schema") != RENDER_SCHEMA:
        raise ColorCompareError("unsupported reference, alignment, or render schema")
    if mask_layers.get("schema") != MASK_LAYER_SCHEMA:
        raise ColorCompareError("unsupported mask-layer schema")
    mask_verification = validate_mask_layers(mask_layer_path)
    if mask_verification["status"] != "pass":
        raise ColorCompareError("mask-layer evidence is invalid: " + "; ".join(mask_verification["errors"]))
    if alignment.get("reference_set_sha256") != sha256(reference_path):
        raise ColorCompareError("alignment does not match the reference-set hash")
    if render.get("reference_set_sha256") != sha256(reference_path) or render.get("alignment_sha256") != sha256(alignment_path):
        raise ColorCompareError("render report does not match the reference set and alignment")
    if mask_layers.get("reference_set_sha256") != sha256(reference_path) or mask_layers.get("alignment_sha256") != sha256(alignment_path) or mask_layers.get("render_report_sha256") != sha256(render_path):
        raise ColorCompareError("mask-layer report does not match the current reference, alignment, and renders")
    masks_path = Path(str(mask_layers.get("reference_masks", ""))).expanduser().resolve()
    try:
        _, masks = validate_mask_manifest(masks_path, reference_path)
    except MaskError as exc:
        raise ColorCompareError(str(exc)) from exc
    views = {row["view_id"]: row for row in reference.get("views") or []}
    renders = {row["view_id"]: row for row in render.get("renders") or []}
    layer_rows = {row["view_id"]: row for row in mask_layers.get("views") or []}
    if not 8 <= len(views) <= 72 or set(views) != set(renders) or set(views) != set(masks) or set(views) != set(layer_rows):
        raise ColorCompareError("reference, render, mask, and layer reports must contain the same 8-72 view IDs")
    incomplete_mask_reviews = [view_id for view_id, row in layer_rows.items() if (row.get("agent_review") or {}).get("status") != "pass"]
    if incomplete_mask_reviews:
        raise ColorCompareError(
            "Step 5 mask-layer Agent review must pass before coordinate/color refinement: "
            + ", ".join(sorted(incomplete_mask_reviews))
        )
    factor = float(render.get("resolution_percentage", 100)) / 100.0
    if not 0 < factor <= 1:
        raise ColorCompareError("render resolution percentage must be greater than 0 and at most 100")
    ensure_new_directory(output)
    evidence_dir = output / "evidence"
    evidence_dir.mkdir()
    rows: list[dict[str, Any]] = []
    for view_id in sorted(views, key=lambda key: float(views[key]["target_yaw_deg"])):
        view = views[view_id]
        reference_file = resolve_reference_image(reference_path, view)
        model_file = Path(str(renders[view_id].get("path", ""))).expanduser().resolve()
        mask_file = Path(str(masks[view_id].get("path", ""))).expanduser().resolve()
        if not model_file.is_file() or sha256(model_file) != renders[view_id].get("sha256"):
            raise ColorCompareError(f"{view_id} model render is missing or changed")
        with Image.open(reference_file) as opened:
            reference_image = opened.convert("RGBA")
        with Image.open(model_file) as opened:
            model_image = opened.convert("RGBA")
        expected_size = (round(reference_image.width * factor), round(reference_image.height * factor))
        if model_image.size != expected_size:
            raise ColorCompareError(f"{view_id} reference and model do not share one projected canvas")
        if reference_image.size != expected_size:
            reference_image = reference_image.resize(expected_size, Image.Resampling.LANCZOS)
        with Image.open(mask_file) as opened:
            reference_mask = opened.convert("L")
        if reference_mask.size != expected_size:
            reference_mask = reference_mask.resize(expected_size, Image.Resampling.NEAREST)
        background_rgb = corner_background(reference_image)
        background = Image.new("RGBA", expected_size, (*background_rgb, 255))
        reference_projection = background.copy()
        reference_projection.paste(reference_image, (0, 0), reference_mask)
        model_projection = Image.alpha_composite(background, model_image)
        blend = Image.blend(reference_projection, model_projection, 0.5)
        difference = ImageChops.difference(reference_projection.convert("RGB"), model_projection.convert("RGB"))
        difference = difference.point(lambda value: min(255, value * 3))
        checker = checkerboard(reference_projection, model_projection, args.checker_size)
        panel = make_panel(reference_projection, model_projection, blend, difference, view_id)
        paths = {
            "reference_projection": evidence_dir / f"{view_id}-reference-projection.png",
            "model_projection": evidence_dir / f"{view_id}-model-projection.png",
            "color_overlay_50_50": evidence_dir / f"{view_id}-color-overlay-50-50.png",
            "color_difference": evidence_dir / f"{view_id}-color-difference.png",
            "coordinate_checkerboard": evidence_dir / f"{view_id}-coordinate-checkerboard.png",
            "coordinate_color_panel": evidence_dir / f"{view_id}-coordinate-color-panel.png",
        }
        reference_projection.save(paths["reference_projection"])
        model_projection.save(paths["model_projection"])
        blend.save(paths["color_overlay_50_50"])
        difference.save(paths["color_difference"])
        checker.save(paths["coordinate_checkerboard"])
        panel.save(paths["coordinate_color_panel"])
        rows.append(
            {
                "view_id": view_id,
                "yaw_deg": float(view["target_yaw_deg"]),
                "canvas": {"width": expected_size[0], "height": expected_size[1], "origin": "top-left", "coordinates": "identical-camera-projection"},
                "background_rgb": list(background_rgb),
                "evidence": {name: {"path": str(path), "sha256": sha256(path)} for name, path in paths.items()},
                "agent_review": {"status": "pending", "notes": ""},
            }
        )
    report = {
        "schema": COMPARE_SCHEMA,
        "created_at": now_utc(),
        "status": "needs-agent-review",
        "reference_set": str(reference_path),
        "reference_set_sha256": sha256(reference_path),
        "alignment": str(alignment_path),
        "alignment_sha256": sha256(alignment_path),
        "render_report": str(render_path),
        "render_report_sha256": sha256(render_path),
        "mask_layer_report": str(mask_layer_path),
        "mask_layer_report_sha256": sha256(mask_layer_path),
        "view_count": len(rows),
        "views": rows,
        "analysis_boundary": "This tool projects and displays reference/model color at identical camera coordinates. It does not score color similarity or decide what to repair; the Agent performs the refinement judgment.",
    }
    report_path = output / "coordinate-color-comparison.json"
    write_json(report_path, report)
    print(json.dumps({"status": report["status"], "report": str(report_path), "views": len(rows)}, ensure_ascii=False))
    return 0


def validate_comparison_report(path: Path) -> dict[str, Any]:
    report = read_json(path)
    errors: list[str] = []
    if report.get("schema") != COMPARE_SCHEMA:
        errors.append(f"unsupported coordinate-color schema: {report.get('schema')}")
    if report.get("status") != "needs-agent-review":
        errors.append("coordinate-color report status is not needs-agent-review")
    rows = report.get("views") if isinstance(report.get("views"), list) else []
    if not 8 <= len(rows) <= 72 or report.get("view_count") != len(rows):
        errors.append("coordinate-color report must contain 8-72 views and a matching count")
    ids = [row.get("view_id") for row in rows if isinstance(row, dict)]
    if len(ids) != len(set(ids)):
        errors.append("coordinate-color view IDs are not unique")
    for label in ("reference_set", "alignment", "render_report", "mask_layer_report"):
        source = Path(str(report.get(label, ""))).expanduser().resolve()
        if not source.is_file() or sha256(source) != report.get(f"{label}_sha256"):
            errors.append(f"{label} is missing or changed")
    for row in rows:
        canvas = row.get("canvas") if isinstance(row.get("canvas"), dict) else {}
        if not canvas.get("width") or not canvas.get("height") or canvas.get("coordinates") != "identical-camera-projection":
            errors.append(f"{row.get('view_id')} does not use one identical projected canvas")
        if (row.get("agent_review") or {}).get("status") not in {"pending", "pass", "fail"}:
            errors.append(f"{row.get('view_id')} has invalid agent_review status")
        for name, evidence in (row.get("evidence") or {}).items():
            evidence_path = Path(str(evidence.get("path", ""))).expanduser().resolve()
            if not evidence_path.is_file() or sha256(evidence_path) != evidence.get("sha256"):
                errors.append(f"{row.get('view_id')} {name} evidence is missing or changed")
    return {
        "schema": VERIFY_SCHEMA,
        "checked_at": now_utc(),
        "status": "pass" if not errors else "fail",
        "report": str(path),
        "report_sha256": sha256(path),
        "view_count": len(rows),
        "errors": errors,
        "meaning": "pass verifies projection coordinates and evidence integrity only; the Agent judges color and refinement",
    }


def command_verify(args: argparse.Namespace) -> int:
    result = validate_comparison_report(Path(args.report).expanduser().resolve())
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "pass" else 2


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    compare = sub.add_parser("compare", help="Project reference and model colors on identical camera coordinates")
    compare.add_argument("--reference-set", required=True)
    compare.add_argument("--alignment", required=True)
    compare.add_argument("--render-report", required=True)
    compare.add_argument("--mask-layer-report", required=True)
    compare.add_argument("--out", required=True)
    compare.add_argument("--checker-size", type=int, default=32)
    compare.set_defaults(func=command_compare)
    verify = sub.add_parser("verify", help="Verify projected-canvas and evidence integrity")
    verify.add_argument("--report", required=True)
    verify.set_defaults(func=command_verify)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return int(args.func(args))
    except (ColorCompareError, MaskError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
