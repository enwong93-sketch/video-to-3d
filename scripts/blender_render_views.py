#!/usr/bin/env python3
"""Render the modeled asset from every calibrated V3D camera."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import bpy

from artifact_safety import safe_output_path, validate_image_size, validate_view_ids


RENDER_SCHEMA = "video-to-3d/render-set/v1"


class RenderError(RuntimeError):
    pass


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--report")
    parser.add_argument("--resolution-percentage", type=int, default=100)
    return parser.parse_args(raw)


def render_all(output: Path, resolution_percentage: int) -> dict:
    if not bpy.data.filepath:
        raise RenderError("open a saved Blender project before rendering")
    if output.exists() and any(output.iterdir()):
        raise RenderError(f"render output directory is not empty: {output}")
    if not 1 <= resolution_percentage <= 100:
        raise RenderError("resolution-percentage must be between 1 and 100")
    model_collection = bpy.data.collections.get("V3D_MODEL")
    if model_collection is None:
        raise RenderError("V3D_MODEL collection is missing")
    model_objects = [obj for obj in model_collection.all_objects if obj.type in {"MESH", "CURVE", "SURFACE", "META", "VOLUME"} and not obj.hide_render]
    if not model_objects:
        raise RenderError("V3D_MODEL has no renderable model objects")
    cameras = sorted(
        [obj for obj in bpy.data.objects if obj.type == "CAMERA" and obj.get("v3d_view_id")],
        key=lambda obj: float(obj.get("v3d_target_yaw_deg", 0.0)),
    )
    expected = int(bpy.context.scene.get("v3d_view_count", 0))
    if len(cameras) != expected or not 8 <= len(cameras) <= 72:
        raise RenderError(f"expected {expected} calibrated cameras, found {len(cameras)}")
    validate_view_ids([{"view_id": str(camera["v3d_view_id"])} for camera in cameras], error_type=RenderError)
    output.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.resolution_percentage = resolution_percentage
    rows = []
    for camera in cameras:
        backgrounds = camera.data.background_images
        if len(backgrounds) != 1 or backgrounds[0].image is None:
            raise RenderError(f"{camera.name} has no calibrated background image")
        image = backgrounds[0].image
        width, height = validate_image_size(image.size[0], image.size[1], count=len(cameras), error_type=RenderError)
        scene.camera = camera
        scene.render.resolution_x = width
        scene.render.resolution_y = height
        view_id = str(camera["v3d_view_id"])
        destination = safe_output_path(output, f"{view_id}.png", error_type=RenderError)
        scene.render.filepath = str(destination)
        bpy.ops.render.render(write_still=True)
        if not destination.is_file() or destination.stat().st_size == 0:
            raise RenderError(f"render did not produce {destination}")
        rows.append(
            {
                "view_id": view_id,
                "camera": camera.name,
                "yaw_deg": float(camera["v3d_target_yaw_deg"]),
                "path": str(destination),
                "sha256": sha256(destination),
                "width": round(width * resolution_percentage / 100),
                "height": round(height * resolution_percentage / 100),
            }
        )
    return {
        "schema": RENDER_SCHEMA,
        "created_at": now_utc(),
        "status": "pass",
        "blend": str(Path(bpy.data.filepath).resolve()),
        "blend_sha256": sha256(Path(bpy.data.filepath)),
        "reference_set_sha256": str(scene.get("v3d_reference_set_sha256", "")),
        "alignment_sha256": str(scene.get("v3d_alignment_sha256", "")),
        "resolution_percentage": resolution_percentage,
        "view_count": len(rows),
        "renders": rows,
    }


def main() -> int:
    args = parse_args()
    output = Path(args.out).expanduser().resolve()
    report_path = Path(args.report).expanduser().resolve() if args.report else output.parent / f"{output.name}-report.json"
    try:
        report = render_all(output, args.resolution_percentage)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({"status": "pass", "report": str(report_path), "views": report["view_count"]}, ensure_ascii=False))
        return 0
    except RenderError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
