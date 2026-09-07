#!/usr/bin/env python3
"""Shared trust-boundary checks for local manifests and generated artifacts."""

from __future__ import annotations

import json
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
