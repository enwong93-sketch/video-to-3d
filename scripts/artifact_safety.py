#!/usr/bin/env python3
"""Shared trust-boundary checks for local manifests and generated artifacts."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Type

MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_IMAGE_SIDE = 8192
MAX_IMAGE_PIXELS = 16_777_216
MAX_AGGREGATE_PIXELS = 600_000_000
VIEW_ID = re.compile(r"^view-[0-9]{3}$")


def read_json_limited(path: Path, *, error_type: Type[Exception] = ValueError) -> dict[str, Any]:
    try:
        if path.stat().st_size > MAX_JSON_BYTES:
            raise error_type(f"JSON exceeds {MAX_JSON_BYTES} bytes: {path}")
        value = json.loads(path.read_text(encoding="utf-8"))
    except error_type:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise error_type(f"cannot read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise error_type(f"JSON root must be an object: {path}")
    return value


def validate_view_ids(rows: Iterable[Any], *, error_type: Type[Exception] = ValueError) -> list[str]:
    ids: list[str] = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("view_id"), str):
            raise error_type("every view requires a string view_id")
        view_id = row["view_id"]
        if not VIEW_ID.fullmatch(view_id):
            raise error_type(f"invalid view_id: {view_id!r}")
        ids.append(view_id)
    if len(ids) != len(set(ids)):
        raise error_type("view IDs must be unique")
    return ids


def safe_output_path(root: Path, filename: str, *, error_type: Type[Exception] = ValueError) -> Path:
    if Path(filename).name != filename or filename in {"", ".", ".."}:
        raise error_type(f"unsafe output filename: {filename!r}")
    resolved_root = root.resolve()
    candidate = (resolved_root / filename).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise error_type(f"output path escapes its directory: {filename!r}") from exc
    return candidate


def validate_image_size(width: Any, height: Any, *, count: int = 1, error_type: Type[Exception] = ValueError) -> tuple[int, int]:
    try:
        w, h = int(width), int(height)
    except (TypeError, ValueError) as exc:
        raise error_type("image dimensions must be integers") from exc
    pixels = w * h
    if w <= 0 or h <= 0 or w > MAX_IMAGE_SIDE or h > MAX_IMAGE_SIDE or pixels > MAX_IMAGE_PIXELS:
        raise error_type(f"image dimensions exceed the safe limit: {w}x{h}")
    if count <= 0 or pixels * count > MAX_AGGREGATE_PIXELS:
        raise error_type("aggregate decoded pixels exceed the safe limit")
    return w, h


def quadrant_rounds(rows: Iterable[Any], *, error_type: Type[Exception] = ValueError) -> list[list[dict[str, Any]]]:
    """Return four-angle review rounds instead of adjacent circular traversal."""
    views = list(rows)
    validate_view_ids(views, error_type=error_type)
    if len(views) < 8 or len(views) > 72 or len(views) % 4:
        raise error_type("view count must be 8-72 and divisible by 4 for quadrant rounds")
    try:
        ordered = sorted(views, key=lambda row: float(row["target_yaw_deg"]) % 360.0)
    except (KeyError, TypeError, ValueError) as exc:
        raise error_type("every view requires numeric target_yaw_deg") from exc
    step = 360.0 / len(ordered)
    for index, row in enumerate(ordered):
        actual = float(row["target_yaw_deg"]) % 360.0
        expected = index * step
        error = min((actual - expected) % 360.0, (expected - actual) % 360.0)
        if not math.isfinite(actual) or error > 0.02:
            raise error_type("quadrant rounds require uniform angles beginning at 0 degrees")
    per_quadrant = len(ordered) // 4
    pivot = max(1, per_quadrant // 2)
    offsets: list[int] = []
    for index in range(pivot):
        offsets.append(index)
        if pivot + index < per_quadrant:
            offsets.append(pivot + index)
    offsets.extend(index for index in range(per_quadrant) if index not in offsets)
    return [
        [ordered[offset + quadrant * per_quadrant] for quadrant in range(4)]
        for offset in offsets
    ]


def quadrant_review_order(rows: Iterable[Any], *, error_type: Type[Exception] = ValueError) -> list[dict[str, Any]]:
    return [row for round_rows in quadrant_rounds(rows, error_type=error_type) for row in round_rows]


def quadrant_order_manifest(rows: Iterable[Any], *, error_type: Type[Exception] = ValueError) -> dict[str, Any]:
    rounds = quadrant_rounds(rows, error_type=error_type)
    return {
        "strategy": "four_quadrant_rounds",
        "rule": "process four views separated by 90 degrees per round; never traverse adjacent angles",
        "rounds": [
            {
                "round": index + 1,
                "view_ids": [row["view_id"] for row in round_rows],
                "yaw_degrees": [float(row["target_yaw_deg"]) % 360.0 for row in round_rows],
            }
            for index, round_rows in enumerate(rounds)
        ],
    }
