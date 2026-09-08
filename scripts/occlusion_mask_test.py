#!/usr/bin/env python3
"""Create reviewed reference masks and place them over model masks at identical coordinates."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageStat

from artifact_safety import quadrant_order_manifest, quadrant_review_order, read_json_limited, safe_output_path, validate_image_size, validate_view_ids


REFERENCE_SCHEMA = "video-to-3d/reference-set/v2"
ALIGNMENT_SCHEMA = "video-to-3d/alignment/v1"
RENDER_SCHEMA = "video-to-3d/render-set/v1"
MASK_SCHEMA = "video-to-3d/reference-masks/v1"
COMPARE_SCHEMA = "video-to-3d/mask-layer-comparison/v3"
VERIFY_SCHEMA = "video-to-3d/mask-layer-verification/v3"
EDGE_SCHEMA = "video-to-3d/numeric-edge-constraints/v1"


class MaskError(RuntimeError):
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
    return read_json_limited(path, error_type=MaskError)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def ensure_new_directory(path: Path) -> None:
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise MaskError(f"output directory is not empty: {path}")
    path.mkdir(parents=True, exist_ok=True)


def resolve_reference_image(reference_path: Path, view: dict[str, Any]) -> Path:
    path = (reference_path.parent / str(view.get("path", ""))).resolve()
    try:
        path.relative_to(reference_path.parent.resolve())
    except ValueError as exc:
        raise MaskError(f"{view.get('view_id')} reference path escapes its directory") from exc
    if not path.is_file() or sha256(path) != view.get("sha256"):
        raise MaskError(f"{view.get('view_id')} reference image is missing or changed")
    return path


def array_bbox(mask: np.ndarray) -> list[int] | None:
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    return [int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)]


def _edge_stats(values: list[int]) -> dict[str, float | int]:
    if not values:
        return {"samples": 0, "mean_abs_px": 0.0, "p95_abs_px": 0.0, "max_abs_px": 0}
    absolute = np.abs(np.asarray(values, dtype=np.int32))
    return {
        "samples": int(absolute.size),
        "mean_abs_px": round(float(absolute.mean()), 6),
        "p95_abs_px": round(float(np.percentile(absolute, 95)), 6),
        "max_abs_px": int(absolute.max()),
    }


def _foreground_runs(indices: np.ndarray) -> list[list[int]]:
    if not len(indices):
        return []
    breaks = np.flatnonzero(np.diff(indices) > 1)
    starts = np.concatenate(([0], breaks + 1))
    ends = np.concatenate((breaks, [len(indices) - 1]))
    return [[int(indices[start]), int(indices[end])] for start, end in zip(starts, ends)]


def numeric_edge_constraints(reference_mask: np.ndarray, model_mask: np.ndarray, world_units_per_pixel: float) -> dict[str, Any]:
    """Measure full silhouette edge coordinates and corrections on one shared camera canvas."""
    if reference_mask.shape != model_mask.shape or reference_mask.ndim != 2:
        raise MaskError("numeric edge masks must share one two-dimensional canvas")
    horizontal: list[dict[str, Any]] = []
    vertical: list[dict[str, Any]] = []
    all_deltas: list[int] = []

    for y in range(reference_mask.shape[0]):
        ref_x = np.flatnonzero(reference_mask[y])
        model_x = np.flatnonzero(model_mask[y])
        if not len(ref_x) and not len(model_x):
            continue
        row: dict[str, Any] = {"y_px": y}
        if len(ref_x):
            row.update({"reference_left_px": int(ref_x[0]), "reference_right_px": int(ref_x[-1]), "reference_runs_px": _foreground_runs(ref_x)})
        if len(model_x):
            row.update({"model_left_px": int(model_x[0]), "model_right_px": int(model_x[-1]), "model_runs_px": _foreground_runs(model_x)})
        if len(ref_x) and len(model_x):
            left_delta = int(model_x[0] - ref_x[0])
            right_delta = int(model_x[-1] - ref_x[-1])
            all_deltas.extend((left_delta, right_delta))
            row.update({
                "left_delta_px": left_delta,
                "right_delta_px": right_delta,
                "left_required_correction_px": -left_delta,
                "right_required_correction_px": -right_delta,
                "left_required_correction_world": round(-left_delta * world_units_per_pixel, 9),
                "right_required_correction_world": round(-right_delta * world_units_per_pixel, 9),
            })
            reference_runs = row["reference_runs_px"]
            model_runs = row["model_runs_px"]
            if len(reference_runs) == len(model_runs):
                run_deltas = [[model_start - ref_start, model_end - ref_end] for (ref_start, ref_end), (model_start, model_end) in zip(reference_runs, model_runs)]
                all_deltas.extend(value for pair in run_deltas for value in pair)
                row["run_edge_deltas_px"] = run_deltas
                row["run_edge_required_corrections_px"] = [[-value for value in pair] for pair in run_deltas]
                row["run_edge_required_corrections_camera_x_world"] = [[round(-value * world_units_per_pixel, 9) for value in pair] for pair in run_deltas]
            else:
                row["run_count_mismatch"] = {"reference": len(reference_runs), "model": len(model_runs)}
        horizontal.append(row)

    for x in range(reference_mask.shape[1]):
        ref_y = np.flatnonzero(reference_mask[:, x])
        model_y = np.flatnonzero(model_mask[:, x])
        if not len(ref_y) and not len(model_y):
            continue
        column: dict[str, Any] = {"x_px": x}
        if len(ref_y):
            column.update({"reference_top_px": int(ref_y[0]), "reference_bottom_px": int(ref_y[-1]), "reference_runs_px": _foreground_runs(ref_y)})
        if len(model_y):
            column.update({"model_top_px": int(model_y[0]), "model_bottom_px": int(model_y[-1]), "model_runs_px": _foreground_runs(model_y)})
        if len(ref_y) and len(model_y):
            top_delta = int(model_y[0] - ref_y[0])
            bottom_delta = int(model_y[-1] - ref_y[-1])
            all_deltas.extend((top_delta, bottom_delta))
            column.update({
                "top_delta_px": top_delta,
                "bottom_delta_px": bottom_delta,
                "top_required_correction_px": -top_delta,
                "bottom_required_correction_px": -bottom_delta,
                "top_required_correction_world": round(-top_delta * world_units_per_pixel, 9),
                "bottom_required_correction_world": round(-bottom_delta * world_units_per_pixel, 9),
                "top_required_correction_camera_y_world": round(top_delta * world_units_per_pixel, 9),
                "bottom_required_correction_camera_y_world": round(bottom_delta * world_units_per_pixel, 9),
            })
            reference_runs = column["reference_runs_px"]
            model_runs = column["model_runs_px"]
            if len(reference_runs) == len(model_runs):
                run_deltas = [[model_start - ref_start, model_end - ref_end] for (ref_start, ref_end), (model_start, model_end) in zip(reference_runs, model_runs)]
                all_deltas.extend(value for pair in run_deltas for value in pair)
                column["run_edge_deltas_px"] = run_deltas
                column["run_edge_required_corrections_px"] = [[-value for value in pair] for pair in run_deltas]
                column["run_edge_required_corrections_camera_y_world"] = [[round(value * world_units_per_pixel, 9) for value in pair] for pair in run_deltas]
            else:
                column["run_count_mismatch"] = {"reference": len(reference_runs), "model": len(model_runs)}
        vertical.append(column)

    reference_bbox = array_bbox(reference_mask)
    model_bbox = array_bbox(model_mask)
    if reference_bbox is None or model_bbox is None:
        raise MaskError("numeric edge analysis requires two non-empty masks")
    intersection = int(np.count_nonzero(reference_mask & model_mask))
    union = int(np.count_nonzero(reference_mask | model_mask))
    xor_pixels = int(np.count_nonzero(reference_mask ^ model_mask))
    bbox_delta = [int(model - reference) for model, reference in zip(model_bbox, reference_bbox)]
    exact = bool(np.array_equal(reference_mask, model_mask))
    return {
        "schema": EDGE_SCHEMA,
        "canvas": {"width": int(reference_mask.shape[1]), "height": int(reference_mask.shape[0])},
        "world_units_per_pixel": round(float(world_units_per_pixel), 12),
        "delta_convention": "model_edge_minus_reference_edge; required correction is the negative delta",
        "coordinate_basis": "pixel +X is camera local +X; pixel +Y is camera local -Y; camera-Y correction reverses the image-Y sign",
        "reference_bbox_px": reference_bbox,
        "model_bbox_px": model_bbox,
        "bbox_delta_px": bbox_delta,
        "bbox_required_correction_px": [-value for value in bbox_delta],
        "bbox_required_correction_world": [round(-value * world_units_per_pixel, 9) for value in bbox_delta],
        "reference_width_px": reference_bbox[2] - reference_bbox[0],
        "reference_height_px": reference_bbox[3] - reference_bbox[1],
        "model_width_px": model_bbox[2] - model_bbox[0],
        "model_height_px": model_bbox[3] - model_bbox[1],
        "width_ratio": round((model_bbox[2] - model_bbox[0]) / (reference_bbox[2] - reference_bbox[0]), 9),
        "height_ratio": round((model_bbox[3] - model_bbox[1]) / (reference_bbox[3] - reference_bbox[1]), 9),
        "intersection_pixels": intersection,
        "union_pixels": union,
        "xor_pixels": xor_pixels,
        "xor_percent_of_union": round(xor_pixels / union * 100.0, 9),
        "iou": round(intersection / union, 12),
        "edge_error": _edge_stats(all_deltas),
        "silhouette_exact_match": exact,
        "numeric_gate": "pass" if exact else "fail",
        "horizontal_scanlines": horizontal,
        "vertical_scanlines": vertical,
    }


def binary_from_image(image: Image.Image, threshold: int) -> Image.Image:
    if image.mode == "RGBA" and image.getchannel("A").getextrema() != (255, 255):
        source = image.getchannel("A")
    else:
        source = image.convert("L")
    return source.point(lambda value: 255 if value >= threshold else 0, mode="L")


def alpha_mask(reference: Image.Image, threshold: int) -> Image.Image:
    alpha = reference.convert("RGBA").getchannel("A")
    if alpha.getextrema() == (255, 255):
        raise MaskError("reference image is fully opaque; alpha mode cannot isolate the character")
    return alpha.point(lambda value: 255 if value >= threshold else 0, mode="L")


def corner_color_mask(reference: Image.Image, threshold: int) -> tuple[Image.Image, tuple[int, int, int]]:
    rgb = reference.convert("RGB")
    sample = max(4, min(rgb.width, rgb.height) // 50)
    patches = (
        rgb.crop((0, 0, sample, sample)),
        rgb.crop((rgb.width - sample, 0, rgb.width, sample)),
        rgb.crop((0, rgb.height - sample, sample, rgb.height)),
        rgb.crop((rgb.width - sample, rgb.height - sample, rgb.width, rgb.height)),
    )
    medians = [ImageStat.Stat(patch).median for patch in patches]
    background = tuple(int(round(float(np.median([row[channel] for row in medians])))) for channel in range(3))
    pixels = np.asarray(rgb, dtype=np.int16)
    delta = np.max(np.abs(pixels - np.asarray(background, dtype=np.int16)), axis=2)
    return Image.fromarray(np.where(delta >= threshold, 255, 0).astype(np.uint8)), background


def mask_review_overlay(reference: Image.Image, mask: Image.Image) -> Image.Image:
    base = reference.convert("RGBA")
    cyan = Image.new("RGBA", base.size, (0, 220, 255, 0))
    cyan.putalpha(mask.point(lambda value: 125 if value else 0))
    return Image.alpha_composite(base, cyan)


def contact_sheet(images: list[Image.Image], labels: list[str], columns: int = 6) -> Image.Image:
    tile_w, tile_h = 240, 240
    columns = max(1, min(columns, len(images)))
    rows = math.ceil(len(images) / columns)
    sheet = Image.new("RGB", (columns * tile_w, rows * tile_h), "black")
    draw = ImageDraw.Draw(sheet)
    for index, (image, label) in enumerate(zip(images, labels)):
        thumb = image.convert("RGB").copy()
        thumb.thumbnail((tile_w - 8, tile_h - 26), Image.Resampling.LANCZOS)
        x = (index % columns) * tile_w + (tile_w - thumb.width) // 2
        y = (index // columns) * tile_h + 22
        sheet.paste(thumb, (x, y))
        draw.text(((index % columns) * tile_w + 6, (index // columns) * tile_h + 5), label, fill="white")
    return sheet


def command_masks(args: argparse.Namespace) -> int:
    reference_path = Path(args.reference_set).expanduser().resolve()
    output = Path(args.out).expanduser().resolve()
    reference = read_json(reference_path)
    if reference.get("schema") != REFERENCE_SCHEMA:
        raise MaskError(f"unsupported reference-set schema: {reference.get('schema')}")
    views = reference.get("views") if isinstance(reference.get("views"), list) else []
    if not 8 <= len(views) <= 72:
        raise MaskError("reference set must contain 8-72 views")
    if not 1 <= args.threshold <= 254:
        raise MaskError("threshold must be between 1 and 254")
    if args.mode == "directory" and not args.mask_dir:
        raise MaskError("directory mode requires --mask-dir")
    supplied_dir = Path(args.mask_dir).expanduser().resolve() if args.mask_dir else None
    ensure_new_directory(output)
    masks_dir = output / "masks"
    review_dir = output / "mask-review"
    masks_dir.mkdir()
    review_dir.mkdir()
    rows: list[dict[str, Any]] = []
    overlays: list[Image.Image] = []
    labels: list[str] = []
    validate_view_ids(views, error_type=MaskError)
    warnings: list[str] = []
    for review_index, view in enumerate(quadrant_review_order(views, error_type=MaskError)):
        view_id = str(view["view_id"])
        reference_file = resolve_reference_image(reference_path, view)
        with Image.open(reference_file) as opened:
            reference_image = opened.convert("RGBA")
        if args.mode == "alpha":
            mask = alpha_mask(reference_image, args.threshold)
            method = "reference_alpha_threshold"
            background = None
        elif args.mode == "corner-color":
            mask, background = corner_color_mask(reference_image, args.threshold)
            method = "draft_corner_color_difference"
        else:
            source_mask = supplied_dir / f"{view_id}.png"
            if not source_mask.is_file():
                raise MaskError(f"missing supplied mask: {source_mask}")
            with Image.open(source_mask) as supplied:
                if supplied.size != reference_image.size:
                    raise MaskError(f"{view_id} supplied mask size does not match the reference")
                mask = binary_from_image(supplied, args.threshold)
            method = "supplied_mask"
            background = None
        mask_array = np.asarray(mask, dtype=np.uint8) > 0
        bbox = array_bbox(mask_array)
        area = int(mask_array.sum())
        if bbox is None or area == 0:
            raise MaskError(f"{view_id} mask is empty")
        if bbox[0] == 0 or bbox[1] == 0 or bbox[2] == mask.width or bbox[3] == mask.height:
            warnings.append(f"{view_id} mask touches a frame edge; inspect crop and segmentation")
        validate_image_size(reference_image.width, reference_image.height, count=len(views), error_type=MaskError)
        mask_path = safe_output_path(masks_dir, f"{view_id}.png", error_type=MaskError)
        mask.save(mask_path)
        overlay = mask_review_overlay(reference_image, mask)
        overlay_path = safe_output_path(review_dir, f"{view_id}-mask-overlay.png", error_type=MaskError)
        overlay.save(overlay_path)
        overlays.append(overlay)
        labels.append(view_id)
        rows.append(
            {
                "view_id": view_id,
                "review_round": review_index // 4 + 1,
                "review_position": review_index % 4 + 1,
                "yaw_deg": float(view["target_yaw_deg"]),
                "path": str(mask_path),
                "sha256": sha256(mask_path),
                "width": mask.width,
                "height": mask.height,
                "bbox_px": bbox,
                "area_pixels": area,
                "method": method,
                "threshold": args.threshold,
                "estimated_background_rgb": list(background) if background else None,
                "visual_status": "pending",
                "visual_notes": "",
                "review_overlay": {"path": str(overlay_path), "sha256": sha256(overlay_path)},
            }
        )
    sheet_path = output / "mask-contact-sheet.png"
    contact_sheet(overlays, labels).save(sheet_path)
    manifest = {
        "schema": MASK_SCHEMA,
        "created_at": now_utc(),
        "status": "needs-visual-review",
        "reference_set": str(reference_path),
        "reference_set_sha256": sha256(reference_path),
        "mode": args.mode,
        "reviewer": "",
        "reviewed_at": "",
        "all_masks_visual_match": {"status": "pending", "evidence_views": labels, "notes": ""},
        "analysis_order": quadrant_order_manifest(views, error_type=MaskError),
        "views": rows,
        "contact_sheet": {"path": str(sheet_path), "sha256": sha256(sheet_path), "order": labels},
        "warnings": warnings,
        "instructions": "Inspect every full-resolution cyan overlay. White mask coverage must match the visible character while preserving true holes. Correct the masks, then mark every view and the all-mask review pass.",
    }
    manifest_path = output / "reference-masks.json"
    write_json(manifest_path, manifest)
    print(json.dumps({"status": manifest["status"], "manifest": str(manifest_path), "views": len(rows), "warnings": warnings}, ensure_ascii=False))
    return 0


def validate_mask_manifest(path: Path, reference_path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    manifest = read_json(path)
    reference = read_json(reference_path)
    errors: list[str] = []
    if manifest.get("schema") != MASK_SCHEMA:
        errors.append(f"unsupported mask schema: {manifest.get('schema')}")
    if manifest.get("reference_set_sha256") != sha256(reference_path):
        errors.append("mask manifest does not match the reference-set hash")
    if manifest.get("status") != "pass":
        errors.append("mask manifest status is not pass")
    reference_views = {row["view_id"]: row for row in reference.get("views") or []}
    rows = manifest.get("views") if isinstance(manifest.get("views"), list) else []
    expected_ids = [row["view_id"] for row in quadrant_review_order(reference.get("views") or [], error_type=MaskError)]
    if [row.get("view_id") for row in rows if isinstance(row, dict)] != expected_ids:
        errors.append("mask views do not follow the four-quadrant review order")
    by_id = {row.get("view_id"): row for row in rows if isinstance(row, dict)}
    if set(by_id) != set(reference_views) or len(rows) != len(reference_views):
        errors.append("mask manifest must contain exactly one row for every reference view")
    pending: list[str] = []
    for view_id, row in by_id.items():
        mask_path = Path(str(row.get("path", ""))).expanduser().resolve()
        if not mask_path.is_file() or sha256(mask_path) != row.get("sha256"):
            errors.append(f"{view_id} mask is missing or changed")
            continue
        with Image.open(mask_path) as opened:
            mask = np.asarray(opened.convert("L"), dtype=np.uint8)
            size = opened.size
        expected = (int(reference_views[view_id]["width"]), int(reference_views[view_id]["height"]))
        if size != expected:
            errors.append(f"{view_id} mask dimensions do not match the reference")
        if not set(int(value) for value in np.unique(mask)).issubset({0, 255}):
            errors.append(f"{view_id} mask is not binary black/white")
        bbox = array_bbox(mask > 0)
        if bbox != row.get("bbox_px") or int(np.count_nonzero(mask)) != row.get("area_pixels"):
            errors.append(f"{view_id} mask bbox or area metadata has changed")
        if bbox and (bbox[0] == 0 or bbox[1] == 0 or bbox[2] == expected[0] or bbox[3] == expected[1]):
            errors.append(f"{view_id} admitted mask touches a frame edge")
        if abs(float(row.get("yaw_deg", 9999)) - float(reference_views[view_id]["target_yaw_deg"])) > 1e-6:
            errors.append(f"{view_id} mask yaw does not match the reference")
        if row.get("visual_status") != "pass":
            pending.append(str(view_id))
        overlay = row.get("review_overlay") if isinstance(row.get("review_overlay"), dict) else {}
        overlay_path = Path(str(overlay.get("path", ""))).expanduser().resolve()
        if not overlay_path.is_file() or sha256(overlay_path) != overlay.get("sha256"):
            errors.append(f"{view_id} mask review overlay is missing or changed")
    if pending:
        errors.append("mask visual_status is not pass for views: " + ", ".join(pending))
    all_masks = manifest.get("all_masks_visual_match") if isinstance(manifest.get("all_masks_visual_match"), dict) else {}
    if all_masks.get("status") != "pass" or set(all_masks.get("evidence_views") or []) != set(reference_views):
        errors.append("all_masks_visual_match must pass and cite every view")
    if not manifest.get("reviewer") or not manifest.get("reviewed_at"):
        errors.append("mask reviewer and reviewed_at are required")
    contact = manifest.get("contact_sheet") if isinstance(manifest.get("contact_sheet"), dict) else {}
    contact_path = Path(str(contact.get("path", ""))).expanduser().resolve()
    if not contact_path.is_file() or sha256(contact_path) != contact.get("sha256") or contact.get("order") != [row.get("view_id") for row in rows]:
        errors.append("mask contact sheet is missing, changed, or out of order")
    if errors:
        raise MaskError("reference masks are not admitted: " + "; ".join(errors))
    return manifest, by_id


def make_layer_overlay(reference_mask: np.ndarray, model_mask: np.ndarray) -> Image.Image:
    overlap = reference_mask & model_mask
    reference_only = reference_mask & ~model_mask
    model_only = model_mask & ~reference_mask
    pixels = np.zeros((*reference_mask.shape, 3), dtype=np.uint8)
    pixels[overlap] = (40, 220, 90)
    pixels[reference_only] = (245, 65, 65)
    pixels[model_only] = (55, 125, 245)
    return Image.fromarray(pixels)


def make_context_overlay(reference: Image.Image, layer_overlay: Image.Image, reference_mask: np.ndarray, model_mask: np.ndarray, view_id: str) -> Image.Image:
    base = reference.convert("RGBA")
    colors = layer_overlay.convert("RGBA")
    visible = reference_mask | model_mask
    colors.putalpha(Image.fromarray(np.where(visible, 165, 0).astype(np.uint8)))
    output = Image.alpha_composite(base, colors)
    draw = ImageDraw.Draw(output)
    draw.rectangle((0, 0, min(output.width, 680), 42), fill=(0, 0, 0, 205))
    draw.text((8, 6), f"{view_id} | green=overlap red=reference-only blue=model-only", fill="white")
    reference_bbox = array_bbox(reference_mask)
    model_bbox = array_bbox(model_mask)
    if reference_bbox:
        draw.rectangle(tuple(reference_bbox), outline=(255, 80, 80, 255), width=2)
    if model_bbox:
        draw.rectangle(tuple(model_bbox), outline=(80, 150, 255, 255), width=2)
    return output


def command_compare(args: argparse.Namespace) -> int:
    reference_path = Path(args.reference_set).expanduser().resolve()
    alignment_path = Path(args.alignment).expanduser().resolve()
    render_path = Path(args.render_report).expanduser().resolve()
    masks_path = Path(args.reference_masks).expanduser().resolve()
    output = Path(args.out).expanduser().resolve()
    if not 1 <= args.model_alpha_threshold <= 254:
        raise MaskError("model-alpha-threshold must be between 1 and 254")
    reference, alignment, render = read_json(reference_path), read_json(alignment_path), read_json(render_path)
    if reference.get("schema") != REFERENCE_SCHEMA or alignment.get("schema") != ALIGNMENT_SCHEMA or render.get("schema") != RENDER_SCHEMA:
        raise MaskError("unsupported reference, alignment, or render schema")
    if alignment.get("reference_set_sha256") != sha256(reference_path):
        raise MaskError("alignment does not match the reference-set hash")
    if render.get("reference_set_sha256") != sha256(reference_path) or render.get("alignment_sha256") != sha256(alignment_path):
        raise MaskError("render report does not match the reference set and alignment")
    _, masks = validate_mask_manifest(masks_path, reference_path)
    views = {row["view_id"]: row for row in reference.get("views") or []}
    renders = {row["view_id"]: row for row in render.get("renders") or []}
    alignments = {row["view_id"]: row for row in alignment.get("views") or []}
    if not 8 <= len(views) <= 72 or set(views) != set(renders) or set(views) != set(masks) or set(views) != set(alignments):
        raise MaskError("reference, alignment, render, and mask manifests must contain the same 8-72 view IDs")
    factor = float(render.get("resolution_percentage", 100)) / 100.0
    if not 0 < factor <= 1:
        raise MaskError("render resolution percentage must be greater than 0 and at most 100")
    ensure_new_directory(output)
    evidence_dir = output / "evidence"
    evidence_dir.mkdir()
    rows: list[dict[str, Any]] = []
    ordered_views = quadrant_review_order(views.values(), error_type=MaskError)
    for review_index, view in enumerate(ordered_views):
        view_id = view["view_id"]
        reference_file = resolve_reference_image(reference_path, view)
        model_file = Path(str(renders[view_id].get("path", ""))).expanduser().resolve()
        mask_file = Path(str(masks[view_id].get("path", ""))).expanduser().resolve()
        if not model_file.is_file() or sha256(model_file) != renders[view_id].get("sha256"):
            raise MaskError(f"{view_id} model render is missing or changed")
        with Image.open(reference_file) as opened:
            reference = opened.convert("RGBA")
        with Image.open(model_file) as opened:
            model = opened.convert("RGBA")
        expected_size = (round(reference.width * factor), round(reference.height * factor))
        if model.size != expected_size:
            raise MaskError(f"{view_id} model render and reference do not share the same scaled canvas")
        if reference.size != expected_size:
            reference = reference.resize(expected_size, Image.Resampling.LANCZOS)
        with Image.open(mask_file) as opened:
            reference_mask_image = opened.convert("L")
        if reference_mask_image.size != expected_size:
            reference_mask_image = reference_mask_image.resize(expected_size, Image.Resampling.NEAREST)
        reference_mask = np.asarray(reference_mask_image, dtype=np.uint8) > 0
        model_mask = np.asarray(model.getchannel("A"), dtype=np.uint8) >= args.model_alpha_threshold
        if not reference_mask.any() or not model_mask.any():
            raise MaskError(f"{view_id} reference or model mask is empty")
        layer = make_layer_overlay(reference_mask, model_mask)
        context = make_context_overlay(reference, layer, reference_mask, model_mask, view_id)
        alignment_row = alignments[view_id]
        try:
            bbox_height = float(alignment_row["subject_bbox_px"][3]) - float(alignment_row["subject_bbox_px"][1])
            target_height = float(alignment_row.get("target_height_m", alignment["target_height_m"]))
            ortho_scale = target_height * float(view["height"]) / bbox_height
            world_units_per_pixel = ortho_scale / expected_size[1]
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
            raise MaskError(f"{view_id} cannot derive numeric pixel-to-world scale") from exc
        numeric = numeric_edge_constraints(reference_mask, model_mask, world_units_per_pixel)
        layer_path = safe_output_path(evidence_dir, f"{view_id}-mask-layer-overlay.png", error_type=MaskError)
        context_path = safe_output_path(evidence_dir, f"{view_id}-mask-layer-overlay-on-reference.png", error_type=MaskError)
        edge_path = safe_output_path(evidence_dir, f"{view_id}-numeric-edge-constraints.json", error_type=MaskError)
        layer.save(layer_path)
        context.save(context_path)
        write_json(edge_path, {"view_id": view_id, "yaw_deg": float(view["target_yaw_deg"]), **numeric})
        numeric_summary = {key: value for key, value in numeric.items() if key not in {"horizontal_scanlines", "vertical_scanlines"}}
        rows.append(
            {
                "view_id": view_id,
                "review_round": review_index // 4 + 1,
                "review_position": review_index % 4 + 1,
                "yaw_deg": float(view["target_yaw_deg"]),
                "canvas": {"width": expected_size[0], "height": expected_size[1], "origin": "top-left", "coordinates": "identical"},
                "reference_mask_bbox_px": array_bbox(reference_mask),
                "model_mask_bbox_px": array_bbox(model_mask),
                "numeric_edge": numeric_summary,
                "evidence": {
                    "mask_layer_overlay": {"path": str(layer_path), "sha256": sha256(layer_path)},
                    "mask_layer_overlay_on_reference": {"path": str(context_path), "sha256": sha256(context_path)},
                    "numeric_edge_constraints": {"path": str(edge_path), "sha256": sha256(edge_path)},
                },
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
        "reference_masks": str(masks_path),
        "reference_masks_sha256": sha256(masks_path),
        "view_count": len(rows),
        "analysis_order": quadrant_order_manifest(views.values(), error_type=MaskError),
        "views": rows,
        "legend": {
            "green": "both mask layers cover the same pixel",
            "red": "reference-mask layer only",
            "blue": "model-mask layer only",
        },
        "numeric_acceptance": "100% silhouette pass requires XOR=0, IoU=1, bbox delta=0, and every scanline edge delta=0 at every admitted angle.",
        "analysis_boundary": "This tool measures exact binary silhouette edges and displays the two masks. Numeric constraints drive shared-model fitting; the Agent still performs visual and 3D-consistency review.",
    }
    report_path = output / "mask-layer-comparison.json"
    write_json(report_path, report)
    print(json.dumps({"status": report["status"], "report": str(report_path), "views": len(rows)}, ensure_ascii=False))
    return 0


def validate_comparison_report(path: Path) -> dict[str, Any]:
    report = read_json(path)
    errors: list[str] = []
    if report.get("schema") != COMPARE_SCHEMA:
        errors.append(f"unsupported mask-layer schema: {report.get('schema')}")
    if report.get("status") != "needs-agent-review":
        errors.append("mask-layer report status is not needs-agent-review")
    rows = report.get("views") if isinstance(report.get("views"), list) else []
    if not 8 <= len(rows) <= 72 or report.get("view_count") != len(rows):
        errors.append("mask-layer report must contain 8-72 views and a matching count")
    ids = [row.get("view_id") for row in rows if isinstance(row, dict)]
    if len(ids) != len(set(ids)):
        errors.append("mask-layer view IDs are not unique")
    for label in ("reference_set", "alignment", "render_report", "reference_masks"):
        source = Path(str(report.get(label, ""))).expanduser().resolve()
        if not source.is_file() or sha256(source) != report.get(f"{label}_sha256"):
            errors.append(f"{label} is missing or changed")
    if any(row.get("review_round") != index // 4 + 1 or row.get("review_position") != index % 4 + 1 for index, row in enumerate(rows) if isinstance(row, dict)):
        errors.append("mask-layer views do not follow the four-quadrant review order")
    for row in rows:
        canvas = row.get("canvas") if isinstance(row.get("canvas"), dict) else {}
        if not canvas.get("width") or not canvas.get("height") or canvas.get("coordinates") != "identical":
            errors.append(f"{row.get('view_id')} canvas is not an identical coordinate space")
        if (row.get("agent_review") or {}).get("status") not in {"pending", "pass", "fail"}:
            errors.append(f"{row.get('view_id')} has invalid agent_review status")
        numeric = row.get("numeric_edge") if isinstance(row.get("numeric_edge"), dict) else {}
        if numeric.get("numeric_gate") not in {"pass", "fail"} or not isinstance(numeric.get("silhouette_exact_match"), bool):
            errors.append(f"{row.get('view_id')} has invalid numeric edge metrics")
        if (row.get("agent_review") or {}).get("status") == "pass" and (
            numeric.get("numeric_gate") != "pass"
            or numeric.get("silhouette_exact_match") is not True
            or numeric.get("xor_pixels") != 0
            or numeric.get("iou") != 1.0
            or numeric.get("bbox_delta_px") != [0, 0, 0, 0]
            or (numeric.get("edge_error") or {}).get("max_abs_px") != 0
        ):
            errors.append(f"{row.get('view_id')} cannot pass before numeric silhouette equality")
        for name, evidence in (row.get("evidence") or {}).items():
            evidence_path = Path(str(evidence.get("path", ""))).expanduser().resolve()
            if not evidence_path.is_file() or sha256(evidence_path) != evidence.get("sha256"):
                errors.append(f"{row.get('view_id')} {name} evidence is missing or changed")
        edge_evidence = (row.get("evidence") or {}).get("numeric_edge_constraints") or {}
        edge_path = Path(str(edge_evidence.get("path", ""))).expanduser().resolve()
        if edge_path.is_file() and sha256(edge_path) == edge_evidence.get("sha256"):
            edge_payload = read_json(edge_path)
            for key in ("numeric_gate", "silhouette_exact_match", "xor_pixels", "iou", "bbox_delta_px", "edge_error"):
                if numeric.get(key) != edge_payload.get(key):
                    errors.append(f"{row.get('view_id')} numeric summary does not match edge evidence")
                    break
    return {
        "schema": VERIFY_SCHEMA,
        "checked_at": now_utc(),
        "status": "pass" if not errors else "fail",
        "report": str(path),
        "report_sha256": sha256(path),
        "view_count": len(rows),
        "errors": errors,
        "meaning": "pass verifies layer alignment and evidence integrity only; the Agent still judges the visual difference",
    }


def command_verify(args: argparse.Namespace) -> int:
    result = validate_comparison_report(Path(args.report).expanduser().resolve())
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "pass" else 2


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    masks = sub.add_parser("masks", help="Create normalized masks and a mandatory visual-review manifest")
    masks.add_argument("--reference-set", required=True)
    masks.add_argument("--out", required=True)
    masks.add_argument("--mode", choices=("alpha", "corner-color", "directory"), required=True)
    masks.add_argument("--mask-dir")
    masks.add_argument("--threshold", type=int, default=16)
    masks.set_defaults(func=command_masks)
    compare = sub.add_parser("compare", help="Place reference and model masks on the same pixel canvas")
    compare.add_argument("--reference-set", required=True)
    compare.add_argument("--alignment", required=True)
    compare.add_argument("--render-report", required=True)
    compare.add_argument("--reference-masks", required=True)
    compare.add_argument("--out", required=True)
    compare.add_argument("--model-alpha-threshold", type=int, default=8)
    compare.set_defaults(func=command_compare)
    verify = sub.add_parser("verify", help="Verify layer coordinates, source hashes, and output evidence")
    verify.add_argument("--report", required=True)
    verify.set_defaults(func=command_verify)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return int(args.func(args))
    except MaskError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
