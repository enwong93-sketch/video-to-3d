#!/usr/bin/env python3
"""Create or verify an angle-calibrated Blender reference-camera project."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector


REFERENCE_SCHEMA = "video-to-3d-model/reference-set/v2"
ALIGNMENT_SCHEMA = "video-to-3d-model/alignment/v1"
SETUP_SCHEMA = "video-to-3d-model/blender-reference-setup/v1"
MIN_ANGLES = 8
MAX_ANGLES = 72


class SetupError(RuntimeError):
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
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SetupError(f"cannot read JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise SetupError(f"JSON root must be an object: {path}")
    return payload


def resolve_under(base: Path, relative: str) -> Path:
    path = (base / relative).resolve()
    try:
        path.relative_to(base.resolve())
    except ValueError as exc:
        raise SetupError(f"reference path escapes the reference-set directory: {relative}") from exc
    return path


def load_contract(reference_path: Path, alignment_path: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    reference = read_json(reference_path)
    alignment = read_json(alignment_path)
    if reference.get("schema") != REFERENCE_SCHEMA:
        raise SetupError(f"unsupported reference-set schema: {reference.get('schema')}")
    if alignment.get("schema") != ALIGNMENT_SCHEMA:
        raise SetupError(f"unsupported alignment schema: {alignment.get('schema')}")
    if alignment.get("reference_set_sha256") != sha256(reference_path):
        raise SetupError("alignment does not match the current reference-set hash")
    views = reference.get("views") if isinstance(reference.get("views"), list) else []
    if not MIN_ANGLES <= len(views) <= MAX_ANGLES:
        raise SetupError(f"reference set must contain {MIN_ANGLES}-{MAX_ANGLES} views")
    try:
        target_height = float(alignment["target_height_m"])
        target_center_z = float(alignment.get("target_center_z_m", target_height / 2.0))
        camera_distance = float(alignment.get("camera_distance_m", max(6.0, target_height * 4.0)))
        drift_limit = float(alignment.get("max_target_height_drift_pct", 1.0))
    except (KeyError, TypeError, ValueError) as exc:
        raise SetupError("alignment requires numeric target_height_m and valid camera settings") from exc
    if not 0.05 <= target_height <= 100.0:
        raise SetupError("target_height_m must be between 0.05 and 100")
    if not math.isfinite(target_center_z) or not math.isfinite(camera_distance) or camera_distance <= 0:
        raise SetupError("target center and camera distance must be finite; distance must be positive")
    if not 0 <= drift_limit <= 5.0:
        raise SetupError("max_target_height_drift_pct must be between 0 and 5")

    aligned_rows = alignment.get("views") if isinstance(alignment.get("views"), list) else []
    aligned_by_id = {row.get("view_id"): row for row in aligned_rows if isinstance(row, dict)}
    expected_ids = [row.get("view_id") for row in views if isinstance(row, dict)]
    if set(aligned_by_id) != set(expected_ids) or len(aligned_rows) != len(expected_ids):
        raise SetupError("alignment must contain exactly one row for every reference view")

    calibrated: list[dict[str, Any]] = []
    for view in views:
        view_id = str(view["view_id"])
        row = aligned_by_id[view_id]
        width = int(view["width"])
        height = int(view["height"])
        try:
            left, top, right, bottom = [float(value) for value in row["subject_bbox_px"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise SetupError(f"{view_id} requires subject_bbox_px [left, top, right, bottom]") from exc
        if not (0 <= left < right <= width and 0 <= top < bottom <= height):
            raise SetupError(f"{view_id} subject_bbox_px is outside its {width}x{height} image")
        declared_height = float(row.get("target_height_m", target_height))
        drift_pct = abs(declared_height - target_height) / target_height * 100.0
        if drift_pct > drift_limit + 1e-9:
            raise SetupError(f"{view_id} target-height drift {drift_pct:.3f}% exceeds {drift_limit:.3f}%")
        image_path = resolve_under(reference_path.parent, str(view["path"]))
        if not image_path.is_file() or sha256(image_path) != view.get("sha256"):
            raise SetupError(f"{view_id} image is missing or has changed")
        bbox_height = bottom - top
        ortho_scale = declared_height * height / bbox_height
        calibrated.append(
            {
                "view_id": view_id,
                "yaw_deg": float(view["target_yaw_deg"]),
                "timestamp_seconds": float(view["timestamp_seconds"]),
                "image": image_path,
                "image_sha256": str(view["sha256"]),
                "width": width,
                "height": height,
                "bbox": [left, top, right, bottom],
                "desired_ndc": [(left + right) / (2.0 * width), 1.0 - (top + bottom) / (2.0 * height)],
                "ortho_scale": ortho_scale,
                "target_height_m": declared_height,
                "target_center_z_m": target_center_z,
                "camera_distance_m": camera_distance,
            }
        )
    return reference, alignment, calibrated


def clear_factory_scene() -> None:
    if bpy.data.filepath:
        raise SetupError("--clear-scene is allowed only in an unsaved factory-startup session")
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for collection in list(bpy.data.collections):
        bpy.data.collections.remove(collection)


def new_collection(name: str) -> bpy.types.Collection:
    if name in bpy.data.collections:
        raise SetupError(f"collection already exists: {name}")
    collection = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(collection)
    return collection


def solve_camera_shift(camera: bpy.types.Object, target: Vector, desired_x: float, desired_y: float) -> tuple[float, float, float]:
    scene = bpy.context.scene
    data = camera.data
    data.shift_x = 0.0
    data.shift_y = 0.0
    base = world_to_camera_view(scene, camera, target)
    epsilon = 0.01
    data.shift_x = epsilon
    sample_x = world_to_camera_view(scene, camera, target)
    data.shift_x = 0.0
    data.shift_y = epsilon
    sample_y = world_to_camera_view(scene, camera, target)
    data.shift_y = 0.0
    j00 = (sample_x.x - base.x) / epsilon
    j10 = (sample_x.y - base.y) / epsilon
    j01 = (sample_y.x - base.x) / epsilon
    j11 = (sample_y.y - base.y) / epsilon
    determinant = j00 * j11 - j01 * j10
    if abs(determinant) < 1e-9:
        raise SetupError("camera-shift calibration became singular")
    delta_x = desired_x - base.x
    delta_y = desired_y - base.y
    data.shift_x = (delta_x * j11 - delta_y * j01) / determinant
    data.shift_y = (j00 * delta_y - j10 * delta_x) / determinant
    solved = world_to_camera_view(scene, camera, target)
    residual_px = math.hypot(
        (solved.x - desired_x) * scene.render.resolution_x,
        (solved.y - desired_y) * scene.render.resolution_y,
    )
    return float(data.shift_x), float(data.shift_y), residual_px


def build_scene(reference_path: Path, alignment_path: Path, blend_out: Path, clear_scene: bool) -> dict[str, Any]:
    if blend_out.exists():
        raise SetupError(f"blend output already exists: {blend_out}")
    reference, alignment, calibrated = load_contract(reference_path, alignment_path)
    if clear_scene:
        clear_factory_scene()
    ref_collection = new_collection("V3D_REFERENCES")
    model_collection = new_collection("V3D_MODEL")
    root = bpy.data.objects.new("V3D_MODEL_ROOT", None)
    model_collection.objects.link(root)
    root.empty_display_type = "PLAIN_AXES"
    root["v3d_target_height_m"] = float(alignment["target_height_m"])
    target = Vector((0.0, 0.0, float(calibrated[0]["target_center_z_m"])))

    scene = bpy.context.scene
    scene["v3d_schema"] = SETUP_SCHEMA
    scene["v3d_reference_set"] = str(reference_path)
    scene["v3d_reference_set_sha256"] = sha256(reference_path)
    scene["v3d_alignment"] = str(alignment_path)
    scene["v3d_alignment_sha256"] = sha256(alignment_path)
    scene["v3d_view_count"] = len(calibrated)
    scene["v3d_target_height_m"] = float(alignment["target_height_m"])
    scene.render.resolution_percentage = 100
    camera_rows: list[dict[str, Any]] = []

    for index, row in enumerate(calibrated):
        scene.render.resolution_x = row["width"]
        scene.render.resolution_y = row["height"]
        scene.render.pixel_aspect_x = 1.0
        scene.render.pixel_aspect_y = 1.0
        yaw = math.radians(row["yaw_deg"])
        distance = row["camera_distance_m"]
        location = Vector((math.sin(yaw) * distance, -math.cos(yaw) * distance, target.z))
        camera_data = bpy.data.cameras.new(f"V3D_CAM_{index:03d}")
        camera_data.type = "ORTHO"
        camera_data.ortho_scale = row["ortho_scale"]
        camera_data.show_background_images = True
        camera = bpy.data.objects.new(f"V3D_CAM_{index:03d}_{row['view_id']}", camera_data)
        ref_collection.objects.link(camera)
        camera.location = location
        camera.rotation_euler = (target - location).to_track_quat("-Z", "Y").to_euler()
        shift_x, shift_y, residual_px = solve_camera_shift(
            camera, target, row["desired_ndc"][0], row["desired_ndc"][1]
        )
        if residual_px > 0.5:
            raise SetupError(f"{row['view_id']} alignment residual {residual_px:.3f}px exceeds 0.5px")
        image = bpy.data.images.load(str(row["image"]), check_existing=False)
        background = camera_data.background_images.new()
        background.image = image
        background.alpha = float(alignment.get("background_alpha", 0.65))
        background.display_depth = "BACK"
        background.frame_method = "FIT"
        background.scale = 1.0
        background.offset = (0.0, 0.0)
        camera["v3d_view_id"] = row["view_id"]
        camera["v3d_target_yaw_deg"] = row["yaw_deg"]
        camera["v3d_timestamp_seconds"] = row["timestamp_seconds"]
        camera["v3d_reference_path"] = str(row["image"])
        camera["v3d_reference_sha256"] = row["image_sha256"]
        camera["v3d_subject_bbox_px"] = row["bbox"]
        camera["v3d_target_height_m"] = row["target_height_m"]
        camera["v3d_alignment_residual_px"] = residual_px
        camera["v3d_calibrated_location"] = list(camera.location)
        camera["v3d_calibrated_rotation_euler"] = list(camera.rotation_euler)
        camera["v3d_calibrated_ortho_scale"] = float(camera_data.ortho_scale)
        camera["v3d_calibrated_shift"] = [shift_x, shift_y]
        camera_rows.append(
            {
                "view_id": row["view_id"],
                "camera": camera.name,
                "yaw_deg": row["yaw_deg"],
                "reference": str(row["image"]),
                "reference_sha256": row["image_sha256"],
                "subject_bbox_px": row["bbox"],
                "ortho_scale": row["ortho_scale"],
                "shift_x": shift_x,
                "shift_y": shift_y,
                "alignment_residual_px": residual_px,
            }
        )

    scene.camera = bpy.data.objects[camera_rows[0]["camera"]]
    blend_out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_out), check_existing=False)
    return {
        "schema": SETUP_SCHEMA,
        "created_at": now_utc(),
        "status": "pass",
        "blend": str(blend_out),
        "blend_sha256": sha256(blend_out),
        "reference_set": str(reference_path),
        "reference_set_sha256": sha256(reference_path),
        "alignment": str(alignment_path),
        "alignment_sha256": sha256(alignment_path),
        "target_height_m": float(alignment["target_height_m"]),
        "view_count": len(camera_rows),
        "cameras": camera_rows,
    }


def verify_scene(reference_path: Path, alignment_path: Path) -> dict[str, Any]:
    errors: list[str] = []
    _, alignment, calibrated = load_contract(reference_path, alignment_path)
    scene = bpy.context.scene
    if scene.get("v3d_schema") != SETUP_SCHEMA:
        errors.append("scene setup schema is missing or unsupported")
    if scene.get("v3d_reference_set_sha256") != sha256(reference_path):
        errors.append("scene reference-set hash does not match")
    if scene.get("v3d_alignment_sha256") != sha256(alignment_path):
        errors.append("scene alignment hash does not match")
    cameras = [obj for obj in bpy.data.objects if obj.type == "CAMERA" and obj.get("v3d_view_id")]
    by_id = {obj.get("v3d_view_id"): obj for obj in cameras}
    if len(cameras) != len(calibrated) or set(by_id) != {row["view_id"] for row in calibrated}:
        errors.append("camera set does not match the calibrated reference views")
    camera_rows: list[dict[str, Any]] = []
    for row in calibrated:
        camera = by_id.get(row["view_id"])
        if camera is None:
            continue
        backgrounds = camera.data.background_images
        if len(backgrounds) != 1 or backgrounds[0].image is None:
            errors.append(f"{row['view_id']} does not have exactly one loaded background image")
            background_path = None
        else:
            background_path = Path(bpy.path.abspath(backgrounds[0].image.filepath)).resolve()
        path = Path(str(camera.get("v3d_reference_path", ""))).expanduser().resolve()
        if not path.is_file() or sha256(path) != camera.get("v3d_reference_sha256"):
            errors.append(f"{row['view_id']} reference image is missing or changed")
        if background_path != path:
            errors.append(f"{row['view_id']} loaded background does not match its recorded reference")
        if camera.name not in bpy.data.collections["V3D_REFERENCES"].objects:
            errors.append(f"{row['view_id']} camera is outside V3D_REFERENCES")
        if abs(float(camera.get("v3d_target_yaw_deg", 999.0)) - row["yaw_deg"]) > 1e-6:
            errors.append(f"{row['view_id']} yaw label has drifted")
        if abs(float(camera.data.ortho_scale) - row["ortho_scale"]) > 1e-6:
            errors.append(f"{row['view_id']} orthographic scale has drifted")
        stored_location = camera.get("v3d_calibrated_location")
        stored_rotation = camera.get("v3d_calibrated_rotation_euler")
        stored_shift = camera.get("v3d_calibrated_shift")
        stored_scale = camera.get("v3d_calibrated_ortho_scale")
        if not stored_location or max(abs(float(a) - float(b)) for a, b in zip(camera.location, stored_location)) > 1e-7:
            errors.append(f"{row['view_id']} camera location has drifted")
        if not stored_rotation or max(abs(float(a) - float(b)) for a, b in zip(camera.rotation_euler, stored_rotation)) > 1e-7:
            errors.append(f"{row['view_id']} camera rotation has drifted")
        if not stored_shift or max(abs(float(a) - float(b)) for a, b in zip((camera.data.shift_x, camera.data.shift_y), stored_shift)) > 1e-7:
            errors.append(f"{row['view_id']} camera shift has drifted")
        if stored_scale is None or abs(float(camera.data.ortho_scale) - float(stored_scale)) > 1e-7:
            errors.append(f"{row['view_id']} stored orthographic scale has drifted")
        if float(camera.get("v3d_alignment_residual_px", 999.0)) > 0.5:
            errors.append(f"{row['view_id']} stored alignment residual exceeds 0.5px")
        camera_rows.append(
            {
                "view_id": row["view_id"],
                "camera": camera.name,
                "reference": str(path),
                "reference_sha256": camera.get("v3d_reference_sha256"),
                "ortho_scale": float(camera.data.ortho_scale),
                "shift_x": float(camera.data.shift_x),
                "shift_y": float(camera.data.shift_y),
            }
        )
    if "V3D_MODEL_ROOT" not in bpy.data.objects:
        errors.append("V3D_MODEL_ROOT is missing")
    else:
        root = bpy.data.objects["V3D_MODEL_ROOT"]
        if root.name not in bpy.data.collections["V3D_MODEL"].objects:
            errors.append("V3D_MODEL_ROOT is outside V3D_MODEL")
        if max(abs(float(value)) for value in (*root.location, *root.rotation_euler)) > 1e-7 or max(abs(float(value) - 1.0) for value in root.scale) > 1e-7:
            errors.append("V3D_MODEL_ROOT transform is not identity")
    return {
        "schema": "video-to-3d-model/blender-reference-verification/v1",
        "checked_at": now_utc(),
        "status": "pass" if not errors else "fail",
        "blend": str(Path(bpy.data.filepath).resolve()) if bpy.data.filepath else "",
        "blend_sha256": sha256(Path(bpy.data.filepath)) if bpy.data.filepath else None,
        "reference_set": str(reference_path),
        "alignment": str(alignment_path),
        "target_height_m": float(alignment["target_height_m"]),
        "view_count": len(camera_rows),
        "cameras": camera_rows,
        "errors": errors,
    }


def parse_args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-set", required=True)
    parser.add_argument("--alignment", required=True)
    parser.add_argument("--blend-out")
    parser.add_argument("--report")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--clear-scene", action="store_true")
    return parser.parse_args(raw)


def main() -> int:
    args = parse_args()
    reference = Path(args.reference_set).expanduser().resolve()
    alignment = Path(args.alignment).expanduser().resolve()
    try:
        if args.verify_only:
            report = verify_scene(reference, alignment)
        else:
            if not args.blend_out:
                raise SetupError("--blend-out is required in setup mode")
            report = build_scene(reference, alignment, Path(args.blend_out).expanduser().resolve(), args.clear_scene)
        report_path = Path(args.report).expanduser().resolve() if args.report else (
            (Path(args.blend_out).expanduser().resolve() if args.blend_out else Path(bpy.data.filepath)).with_suffix(".setup-report.json")
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({"status": report["status"], "report": str(report_path), "view_count": report["view_count"], "errors": report.get("errors", [])}, ensure_ascii=False))
        return 0 if report["status"] == "pass" else 2
    except SetupError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
