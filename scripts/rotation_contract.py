#!/usr/bin/env python3
"""Shared, deterministic validation for observed turntable timing."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any


OBSERVATIONS_SCHEMA = "video-to-3d-model/rotation-observations/v1"
AUDIT_SCHEMA = "video-to-3d-model/rotation-audit/v1"
MIN_ORIENTATION_BANDS = 8
MAX_OBSERVATIONS = 73


class RotationContractError(ValueError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_observations(payload: dict[str, Any], source_hash: str | None = None) -> dict[str, Any]:
    """Validate source-grounded observations and calculate constant-speed residuals."""
    errors: list[str] = []
    if payload.get("schema") != OBSERVATIONS_SCHEMA:
        errors.append(f"unsupported observations schema: {payload.get('schema')}")

    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    if source_hash and source.get("sha256") != source_hash:
        errors.append("source video hash does not match observations")

    turn = payload.get("turn") if isinstance(payload.get("turn"), dict) else {}
    try:
        start = float(turn["start_seconds"])
        end = float(turn["end_seconds"])
        front = float(turn["front_time_seconds"])
    except (KeyError, TypeError, ValueError):
        start = end = front = math.nan
        errors.append("turn requires numeric start_seconds, end_seconds, and front_time_seconds")
    direction = turn.get("direction")
    if direction not in {"clockwise", "counterclockwise"}:
        errors.append("turn.direction must be clockwise or counterclockwise")
    if not all(math.isfinite(value) for value in (start, end, front)) or end <= start:
        errors.append("turn interval must be finite and positive")
    elif abs(front - start) > 0.05:
        errors.append("front_time_seconds must be within 0.05 seconds of the first front endpoint")

    limits = payload.get("limits") if isinstance(payload.get("limits"), dict) else {}
    try:
        max_limit = float(limits.get("max_error_deg", 2.0))
        rms_limit = float(limits.get("rms_error_deg", 1.0))
    except (TypeError, ValueError):
        max_limit = rms_limit = math.nan
        errors.append("uniformity limits must be numeric")
    if not math.isfinite(max_limit) or max_limit <= 0 or max_limit > 10:
        errors.append("max_error_deg must be greater than 0 and at most 10")
    if not math.isfinite(rms_limit) or rms_limit <= 0 or rms_limit > max_limit:
        errors.append("rms_error_deg must be greater than 0 and at most max_error_deg")

    raw_rows = payload.get("observations") if isinstance(payload.get("observations"), list) else []
    if len(raw_rows) > MAX_OBSERVATIONS:
        errors.append(f"observations must contain at most {MAX_OBSERVATIONS} rows")
        raw_rows = raw_rows[:MAX_OBSERVATIONS]
    parsed: list[dict[str, Any]] = []
    for index, row in enumerate(raw_rows):
        if not isinstance(row, dict):
            errors.append(f"observation {index} is not an object")
            continue
        try:
            timestamp = float(row["timestamp_seconds"])
            turn_deg = float(row["turn_deg"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"observation {index} requires numeric timestamp_seconds and turn_deg")
            continue
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        if not evidence.get("path") or not evidence.get("sha256"):
            errors.append(f"observation {index} requires evidence path and SHA-256")
        parsed.append({"timestamp_seconds": timestamp, "turn_deg": turn_deg, "evidence": evidence})

    if len(parsed) < MIN_ORIENTATION_BANDS + 1:
        errors.append("at least 8 distinct orientation bands plus the closing front observation are required")
    ordered = sorted(parsed, key=lambda row: row["turn_deg"])
    if parsed != ordered:
        errors.append("observations must be ordered by increasing turn_deg")
    if ordered:
        if abs(ordered[0]["turn_deg"]) > 0.02:
            errors.append("the first observation must be turn_deg 0")
        if abs(ordered[-1]["turn_deg"] - 360.0) > 0.02:
            errors.append("the final observation must be turn_deg 360")
        for previous, current in zip(ordered, ordered[1:]):
            if current["turn_deg"] <= previous["turn_deg"]:
                errors.append("turn_deg values must be strictly increasing")
                break
            if current["timestamp_seconds"] <= previous["timestamp_seconds"]:
                errors.append("observation timestamps must be strictly increasing")
                break
        bands = {round(row["turn_deg"] % 360.0, 3) for row in ordered[:-1]}
        if len(bands) < MIN_ORIENTATION_BANDS:
            errors.append("fewer than 8 distinct observed orientation bands")

    residuals: list[dict[str, float]] = []
    if ordered and math.isfinite(start) and math.isfinite(end) and end > start:
        duration = end - start
        for row in ordered:
            expected_timestamp = start + duration * row["turn_deg"] / 360.0
            error_deg = (row["timestamp_seconds"] - expected_timestamp) / duration * 360.0
            residuals.append(
                {
                    "turn_deg": round(row["turn_deg"], 6),
                    "timestamp_seconds": round(row["timestamp_seconds"], 6),
                    "expected_timestamp_seconds": round(expected_timestamp, 6),
                    "angular_error_deg": round(error_deg, 6),
                }
            )
    absolute = [abs(row["angular_error_deg"]) for row in residuals]
    max_error = max(absolute) if absolute else math.inf
    rms_error = math.sqrt(sum(value * value for value in absolute) / len(absolute)) if absolute else math.inf
    if math.isfinite(max_limit) and max_error > max_limit + 1e-9:
        errors.append(f"maximum angular residual {max_error:.3f} exceeds {max_limit:.3f} degrees")
    if math.isfinite(rms_limit) and rms_error > rms_limit + 1e-9:
        errors.append(f"RMS angular residual {rms_error:.3f} exceeds {rms_limit:.3f} degrees")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "turn": {
            "start_seconds": start,
            "end_seconds": end,
            "front_time_seconds": front,
            "direction": direction,
        },
        "limits": {"max_error_deg": max_limit, "rms_error_deg": rms_limit},
        "metrics": {
            "observed_orientation_bands": max(0, len(ordered) - 1),
            "max_error_deg": round(max_error, 6) if math.isfinite(max_error) else None,
            "rms_error_deg": round(rms_error, 6) if math.isfinite(rms_error) else None,
        },
        "residuals": residuals,
    }
