#!/usr/bin/env python3
"""Build provenance-preserving multi-angle reference sets from character turntable videos."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any

from artifact_safety import quadrant_order_manifest, quadrant_review_order, validate_image_size, validate_view_ids
from rotation_audit import verify_payload as verify_rotation_audit
from rotation_contract import AUDIT_SCHEMA


SCHEMA = "video-to-3d/reference-set/v2"
REVIEW_SCHEMA = "video-to-3d/source-review/v2"
REPORT_SCHEMA = "video-to-3d/reference-verification/v2"
ANCHORS_SCHEMA = "video-to-3d/angle-anchors/v1"
MIN_ANGLES = 8
MAX_ANGLES = 72
REQUIRED_GATES = (
    "one_character",
    "full_body_all_views",
    "a_pose_stable",
    "identity_consistent",
    "complete_rotation",
    "hands_visible",
    "feet_visible",
    "no_action_motion",
    "chirality_consistent",
    "accessories_continuous",
    "overlays_recorded",
)
BLUR_RE = re.compile(r"blur mean:\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)


class IntakeError(RuntimeError):
    pass


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], *, capture: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
            timeout=120,
        )
    except FileNotFoundError as exc:
        raise IntakeError(f"Required executable is unavailable: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise IntakeError(f"Command failed ({command[0]}): {detail[-2000:]}") from exc


def tool_version(name: str) -> str:
    result = run([name, "-version"])
    return (result.stdout or result.stderr).splitlines()[0].strip()


def ffprobe(video: Path) -> dict[str, Any]:
    result = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(video),
        ]
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise IntakeError("ffprobe returned invalid JSON") from exc
    streams = [row for row in payload.get("streams", []) if row.get("codec_type") == "video"]
    if not streams:
        raise IntakeError("No video stream found")
    return payload


def video_facts(video: Path) -> dict[str, Any]:
    payload = ffprobe(video)
    stream = next(row for row in payload["streams"] if row.get("codec_type") == "video")
    duration_text = stream.get("duration") or payload.get("format", {}).get("duration")
    try:
        duration = float(duration_text)
    except (TypeError, ValueError) as exc:
        raise IntakeError("Video duration is unavailable") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise IntakeError("Video duration must be positive")
    rate_text = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1"
    try:
        frame_rate = float(Fraction(rate_text))
    except (ValueError, ZeroDivisionError):
        frame_rate = 0.0
    width, height = validate_image_size(stream.get("width"), stream.get("height"), error_type=IntakeError)
    return {
        "duration_seconds": duration,
        "width": width,
        "height": height,
        "frame_rate": frame_rate,
        "frame_rate_raw": rate_text,
        "codec": stream.get("codec_name"),
        "pixel_format": stream.get("pix_fmt"),
    }


def ensure_video(path_text: str) -> Path:
    video = Path(path_text).expanduser().resolve()
    if not video.is_file():
        raise IntakeError(f"Video does not exist: {video}")
    return video


def ensure_new_output(path_text: str) -> Path:
    out = Path(path_text).expanduser().resolve()
    if out.exists() and any(out.iterdir()):
        raise IntakeError(f"Output directory is not empty; use a new directory: {out}")
    out.mkdir(parents=True, exist_ok=True)
    return out


def extract_frame(video: Path, timestamp: float, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video),
            "-ss",
            f"{timestamp:.6f}",
            "-map",
            "0:v:0",
            "-an",
            "-sn",
            "-dn",
            "-frames:v",
            "1",
            str(destination),
        ]
    )
    if not destination.is_file() or destination.stat().st_size == 0:
        raise IntakeError(f"Frame extraction produced no readable file at {timestamp:.6f}s")


def image_facts(path: Path) -> dict[str, Any]:
    result = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,codec_name",
            "-of",
            "json",
            str(path),
        ]
    )
    data = json.loads(result.stdout)
    stream = (data.get("streams") or [{}])[0]
    return {
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "codec": stream.get("codec_name"),
    }


def blur_mean(path: Path) -> float:
    proc = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(path),
            "-vf",
            "blurdetect=block_width=32:block_height=32:block_pct=80",
            "-f",
            "null",
            os.devnull,
        ],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise IntakeError(f"ffmpeg blurdetect failed for {path}: {proc.stderr[-1000:]}")
    match = BLUR_RE.search(proc.stderr)
    if not match:
        raise IntakeError("This ffmpeg build did not return a blurdetect score")
    return float(match.group(1))


def make_contact_sheet(images: list[Path], destination: Path, columns: int) -> None:
    if not images:
        raise IntakeError("Cannot make an empty contact sheet")
    columns = max(1, min(columns, len(images)))
    rows = math.ceil(len(images) / columns)
    staging = destination.parent / f".{destination.stem}-inputs"
    if staging.exists() and any(staging.iterdir()):
        raise IntakeError(f"Contact-sheet staging directory is not empty: {staging}")
    staging.mkdir(parents=True, exist_ok=True)
    for index, source in enumerate(images):
        target = staging / f"sheet-{index:03d}.png"
        try:
            os.link(source, target)
        except OSError:
            shutil.copy2(source, target)
    filter_text = (
        "scale=260:260:force_original_aspect_ratio=decrease,"
        "pad=260:260:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"tile={columns}x{rows}:nb_frames={len(images)}:padding=4:margin=4"
    )
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-framerate",
            "1",
            "-start_number",
            "0",
            "-i",
            str(staging / "sheet-%03d.png"),
            "-vf",
            filter_text,
            "-frames:v",
            "1",
            str(destination),
        ]
    )


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def bounded_interval(facts: dict[str, Any], start: float, end: float | None) -> tuple[float, float]:
    duration = float(facts["duration_seconds"])
    actual_end = duration if end is None else end
    if start < 0 or actual_end > duration + 0.001 or actual_end <= start:
        raise IntakeError(f"Invalid interval [{start}, {actual_end}] for {duration:.6f}s video")
    return start, min(actual_end, duration)


def evenly_spaced(start: float, end: float, count: int) -> list[float]:
    if count < 2:
        return [(start + end) / 2]
    span = end - start
    return [start + span * (index + 0.5) / count for index in range(count)]


def normalize_yaw(value: float) -> float:
    result = value % 360.0
    return 0.0 if math.isclose(result, 360.0, abs_tol=1e-7) else result


def wrapped_time(start: float, period: float, phase_seconds: float) -> float:
    return start + ((phase_seconds - start) % period)


def candidate_offsets(count: int, bin_seconds: float, radius_seconds: float | None = None) -> list[float]:
    if count <= 1:
        return [0.0]
    radius = min(bin_seconds * 0.20, radius_seconds) if radius_seconds is not None else bin_seconds * 0.20
    return [(-radius + 2 * radius * index / (count - 1)) for index in range(count)]


def load_anchors(
    path: Path,
    angles: int,
    start: float,
    end: float,
    source_hash: str | None = None,
) -> list[dict[str, float]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntakeError(f"Cannot read anchors JSON: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != ANCHORS_SCHEMA:
        raise IntakeError(f"Anchors must use schema {ANCHORS_SCHEMA}")
    if source_hash and (payload.get("source") or {}).get("sha256") != source_hash:
        raise IntakeError("Anchor source hash does not match the video")
    rows = payload.get("anchors")
    if not isinstance(rows, list) or len(rows) != angles:
        raise IntakeError(f"Anchors must contain exactly {angles} entries")
    parsed: list[dict[str, float]] = []
    for row in rows:
        try:
            yaw = normalize_yaw(float(row["yaw_deg"]))
            timestamp = float(row["timestamp_seconds"])
        except (KeyError, TypeError, ValueError) as exc:
            raise IntakeError("Each anchor needs numeric yaw_deg and timestamp_seconds") from exc
        if not start <= timestamp < end:
            raise IntakeError(f"Anchor timestamp {timestamp} is outside [{start}, {end})")
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        evidence_path = Path(str(evidence.get("path", ""))).expanduser().resolve()
        if not evidence_path.is_file() or sha256(evidence_path) != evidence.get("sha256"):
            raise IntakeError(f"Anchor {yaw:.3f} evidence frame is missing or has changed")
        parsed.append({"yaw_deg": yaw, "timestamp_seconds": timestamp})
    ordered = sorted(parsed, key=lambda row: row["yaw_deg"])
    expected_step = 360.0 / angles
    for index, row in enumerate(ordered):
        expected = index * expected_step
        if abs(row["yaw_deg"] - expected) > 0.02:
            raise IntakeError(f"Anchor yaw {row['yaw_deg']} does not match expected {expected}")
    if len({round(row["timestamp_seconds"], 6) for row in ordered}) != angles:
        raise IntakeError("Anchor timestamps must be unique")
    return ordered


def load_uniform_audit(path: Path, video: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    report = verify_rotation_audit(path, video)
    if report["status"] != "pass":
        raise IntakeError("Rotation audit failed: " + "; ".join(report["errors"]))
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != AUDIT_SCHEMA:
        raise IntakeError(f"Rotation audit must use schema {AUDIT_SCHEMA}")
    return payload, report


def command_probe(args: argparse.Namespace) -> int:
    video = ensure_video(args.video)
    out = ensure_new_output(args.out)
    facts = video_facts(video)
    start, end = bounded_interval(facts, args.start, args.end)
    if not 16 <= args.frames <= 160:
        raise IntakeError("Probe frame count must be between 16 and 160")
    frames_dir = out / "probe-frames"
    timestamps = evenly_spaced(start, end, args.frames)
    entries = []
    images = []
    for index, timestamp in enumerate(timestamps):
        frame = frames_dir / f"probe-{index:03d}.png"
        extract_frame(video, timestamp, frame)
        images.append(frame)
        entries.append(
            {
                "probe_id": f"probe-{index:03d}",
                "timestamp_seconds": round(timestamp, 6),
                "path": frame.relative_to(out).as_posix(),
                "sha256": sha256(frame),
                **image_facts(frame),
            }
        )
    sheet = out / "probe-contact-sheet.png"
    make_contact_sheet(images, sheet, args.columns)
    payload = {
        "schema": "video-to-3d/probe/v2",
        "created_at": now_utc(),
        "source": {"path": str(video), "sha256": sha256(video), **facts},
        "interval": {"start_seconds": start, "end_seconds": end},
        "frames": entries,
        "contact_sheet": {
            "path": sheet.relative_to(out).as_posix(),
            "sha256": sha256(sheet),
            "order": [row["probe_id"] for row in entries],
        },
        "tools": {"ffmpeg": tool_version("ffmpeg"), "ffprobe": tool_version("ffprobe")},
        "next_action": "inspect source frames, record real angle observations, then run rotation_audit.py",
    }
    write_json(out / "probe-index.json", payload)
    print(json.dumps({"status": "ok", "output": str(out), "frames": len(entries)}, ensure_ascii=False))
    return 0


def uniform_targets(
    angles: int,
    start: float,
    end: float,
    front_time: float,
    direction: str,
) -> list[dict[str, float]]:
    period = end - start
    sign = 1.0 if direction == "clockwise" else -1.0
    rows = []
    for temporal_index in range(angles):
        target_time = wrapped_time(start, period, front_time + temporal_index * period / angles)
        yaw = normalize_yaw(sign * temporal_index * 360.0 / angles)
        rows.append({"yaw_deg": yaw, "timestamp_seconds": target_time})
    return sorted(rows, key=lambda row: row["yaw_deg"])


def review_template(view_ids: list[str]) -> dict[str, Any]:
    return {
        "schema": REVIEW_SCHEMA,
        "reviewer": "",
        "reviewed_at": "",
        "instructions": "Inspect every admitted view at full resolution; replace pending with pass or fail and cite view IDs.",
        "all_views_read_back": {"status": "pending", "evidence_views": view_ids, "notes": ""},
        "gates": {
            name: {"status": "pending", "evidence_views": [], "notes": ""} for name in REQUIRED_GATES
        },
        "chirality": {
            "character_left_profile_view": "",
            "character_right_profile_view": "",
            "notes": "",
        },
    }


def command_build(args: argparse.Namespace) -> int:
    video = ensure_video(args.video)
    facts = video_facts(video)
    if not MIN_ANGLES <= args.angles <= MAX_ANGLES:
        raise IntakeError(f"Angles must be between {MIN_ANGLES} and {MAX_ANGLES}")
    if args.angles % 4:
        raise IntakeError("Angles must be divisible by 4 for four-quadrant review rounds")
    if not 1 <= args.candidates <= 9 or args.candidates % 2 == 0:
        raise IntakeError("Candidates must be an odd number from 1 to 9")
    if not 0 <= args.candidate_yaw_radius_deg <= 2.0:
        raise IntakeError("candidate-yaw-radius-deg must be between 0 and 2 degrees")
    if args.anchors_json and args.rotation_audit:
        raise IntakeError("Use either --rotation-audit or --anchors-json, not both")
    source_hash = sha256(video)
    timing_evidence: dict[str, Any]
    if args.anchors_json:
        if any(value is None for value in (args.start, args.end, args.front_time, args.direction)):
            raise IntakeError("Per-angle anchors require --start, --end, --front-time, and --direction")
        start, end = bounded_interval(facts, args.start, args.end)
        front_time = float(args.front_time)
        direction = str(args.direction)
        if not start <= front_time < end:
            raise IntakeError("front-time must fall inside the selected interval")
        anchors_path = Path(args.anchors_json).expanduser().resolve()
        targets = load_anchors(anchors_path, args.angles, start, end, source_hash)
        selection_mode = "observed-per-angle-timecodes"
        offsets = [0.0]
        timing_evidence = {
            "kind": "per_angle_observed_anchors",
            "path": str(anchors_path),
            "sha256": sha256(anchors_path),
        }
    elif args.rotation_audit:
        audit_path = Path(args.rotation_audit).expanduser().resolve()
        audit, audit_report = load_uniform_audit(audit_path, video)
        turn = audit_report["turn"]
        start, end = bounded_interval(facts, float(turn["start_seconds"]), float(turn["end_seconds"]))
        front_time = float(turn["front_time_seconds"])
        direction = str(turn["direction"])
        targets = uniform_targets(args.angles, start, end, front_time, direction)
        selection_mode = "measured-uniform-timecodes"
        radius_seconds = (end - start) * float(args.candidate_yaw_radius_deg) / 360.0
        offsets = candidate_offsets(args.candidates, (end - start) / args.angles, radius_seconds)
        timing_evidence = {
            "kind": "measured_uniform_rotation_audit",
            "path": str(audit_path),
            "sha256": sha256(audit_path),
            "metrics": audit.get("metrics"),
        }
    else:
        raise IntakeError("Build requires either --rotation-audit or --anchors-json; prompt wording is not timing proof")

    estimated_frames = (end - start) * float(facts.get("frame_rate") or 0)
    if estimated_frames and estimated_frames < args.angles:
        raise IntakeError(
            f"Selected interval has only about {estimated_frames:.1f} frames for {args.angles} angles"
        )

    out = ensure_new_output(args.out)

    views_dir = out / "views"
    candidates_dir = out / "candidates"
    views: list[dict[str, Any]] = []
    sign = 1.0 if direction == "clockwise" else -1.0
    period = end - start
    for view_index, target in enumerate(targets):
        yaw = float(target["yaw_deg"])
        target_time = float(target["timestamp_seconds"])
        scored = []
        for candidate_index, offset in enumerate(offsets):
            timestamp = wrapped_time(start, period, target_time + offset)
            candidate = candidates_dir / f"yaw-{yaw:06.2f}" / f"candidate-{candidate_index:02d}.png"
            extract_frame(video, timestamp, candidate)
            score = blur_mean(candidate)
            scored.append(
                {
                    "timestamp_seconds": round(timestamp, 6),
                    "offset_seconds": round(offset, 6),
                    "blur_mean": score,
                    "path": candidate.relative_to(out).as_posix(),
                    "sha256": sha256(candidate),
                }
            )
        chosen = min(scored, key=lambda row: (row["blur_mean"], abs(row["offset_seconds"])))
        selected_time = float(chosen["timestamp_seconds"])
        selected_yaw = normalize_yaw(yaw + sign * float(chosen["offset_seconds"]) / period * 360.0)
        view_id = f"view-{view_index:03d}"
        selected = views_dir / f"{view_id}-yaw-{yaw:06.2f}.png"
        selected.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out / chosen["path"], selected)
        facts_image = image_facts(selected)
        view = {
            "view_id": view_id,
            "target_yaw_deg": round(yaw, 6),
            "selected_yaw_estimate_deg": round(selected_yaw, 6),
            "yaw_error_estimate_deg": round(
                min((selected_yaw - yaw) % 360.0, (yaw - selected_yaw) % 360.0), 6
            ),
            "timestamp_seconds": round(selected_time, 6),
            "method": "source_video_frame",
            "path": selected.relative_to(out).as_posix(),
            "sha256": sha256(selected),
            "blur_mean": chosen["blur_mean"],
            "selection": "lowest_blur_mean_then_nearest_target",
            "candidates": scored,
            **facts_image,
        }
        views.append(view)

    if len({row["sha256"] for row in views}) != len(views):
        raise IntakeError("Duplicate admitted source frames detected; choose a longer/cleaner interval")
    review_views = quadrant_review_order(views, error_type=IntakeError)
    analysis_order = quadrant_order_manifest(views, error_type=IntakeError)
    sheet = out / "contact-sheet.png"
    make_contact_sheet([out / row["path"] for row in review_views], sheet, args.columns)
    primary = min(views, key=lambda row: abs(float(row["target_yaw_deg"])))
    payload = {
        "schema": SCHEMA,
        "created_at": now_utc(),
        "source": {"path": str(video), "sha256": source_hash, **facts},
        "capture": {
            "start_seconds": start,
            "end_seconds": end,
            "front_time_seconds": front_time,
            "direction": direction,
            "selection_mode": selection_mode,
            "requested_angles": args.angles,
            "candidate_count_per_angle": len(offsets),
            "candidate_yaw_radius_deg": args.candidate_yaw_radius_deg if len(offsets) > 1 else 0.0,
            "uniform_yaw_step_deg": 360.0 / args.angles,
        },
        "timing_evidence": timing_evidence,
        "primary_reference": primary["path"],
        "views": views,
        "analysis_order": analysis_order,
        "contact_sheet": {
            "path": sheet.relative_to(out).as_posix(),
            "sha256": sha256(sheet),
            "order": [row["view_id"] for row in review_views],
        },
        "provenance": {
            "admitted_view_kind": "decoded_source_frame",
            "synthetic_or_interpolated_views": False,
            "pixel_transform": "none; source resolution preserved",
            "tools": {"ffmpeg": tool_version("ffmpeg"), "ffprobe": tool_version("ffprobe")},
            "script_sha256": sha256(Path(__file__).resolve()),
            "python": platform.python_version(),
        },
    }
    write_json(out / "reference-set.json", payload)
    write_json(out / "review.json", review_template([row["view_id"] for row in review_views]))
    print(
        json.dumps(
            {
                "status": "needs-visual-review",
                "output": str(out),
                "views": len(views),
                "primary_reference": str(out / primary["path"]),
            },
            ensure_ascii=False,
        )
    )
    return 0


def resolve_under(base: Path, relative: str) -> Path:
    candidate = (base / relative).resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError as exc:
        raise IntakeError(f"Manifest path escapes its directory: {relative}") from exc
    return candidate


def verification(reference_path: Path, review_path: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        reference = json.loads(reference_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntakeError(f"Cannot read reference set: {reference_path}") from exc
    try:
        review = json.loads(review_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntakeError(f"Cannot read review: {review_path}") from exc
    if reference.get("schema") != SCHEMA:
        errors.append(f"unsupported reference schema: {reference.get('schema')}")
    if review.get("schema") != REVIEW_SCHEMA:
        errors.append(f"unsupported review schema: {review.get('schema')}")
    base = reference_path.parent.resolve()
    source = reference.get("source") or {}
    source_path: Path | None = None
    try:
        source_path = Path(str(source["path"])).expanduser().resolve()
        if not source_path.is_file():
            errors.append(f"source video is missing: {source_path}")
        elif sha256(source_path) != source.get("sha256"):
            errors.append("source video hash mismatch")
    except (KeyError, OSError, TypeError, ValueError) as exc:
        errors.append(f"invalid source video record: {exc}")
    views = reference.get("views") if isinstance(reference.get("views"), list) else []
    if not MIN_ANGLES <= len(views) <= MAX_ANGLES:
        errors.append(f"view count {len(views)} is outside {MIN_ANGLES}-{MAX_ANGLES}")
    capture = reference.get("capture") or {}
    if capture.get("requested_angles") != len(views):
        errors.append("capture.requested_angles does not match the admitted view count")
    timing = reference.get("timing_evidence") if isinstance(reference.get("timing_evidence"), dict) else {}
    timing_path = Path(str(timing.get("path", ""))).expanduser().resolve()
    if not timing_path.is_file():
        errors.append("timing evidence is missing")
    elif sha256(timing_path) != timing.get("sha256"):
        errors.append("timing evidence hash mismatch")
    elif source_path and source_path.is_file():
        if timing.get("kind") == "measured_uniform_rotation_audit":
            audit_report = verify_rotation_audit(timing_path, source_path)
            if audit_report["status"] != "pass":
                errors.append("rotation audit no longer passes: " + "; ".join(audit_report["errors"]))
        elif timing.get("kind") == "per_angle_observed_anchors":
            try:
                load_anchors(
                    timing_path,
                    len(views),
                    float(capture["start_seconds"]),
                    float(capture["end_seconds"]),
                    str(source.get("sha256")),
                )
            except (KeyError, TypeError, ValueError, IntakeError) as exc:
                errors.append(f"per-angle timing evidence is invalid: {exc}")
        else:
            errors.append(f"unsupported timing evidence kind: {timing.get('kind')}")
    try:
        ids = validate_view_ids(views, error_type=IntakeError)
        expected_order = quadrant_order_manifest(views, error_type=IntakeError)
        if reference.get("analysis_order") != expected_order:
            errors.append("analysis_order does not match four-quadrant rounds")
    except IntakeError as exc:
        errors.append(str(exc))
        ids = [row.get("view_id") for row in views if isinstance(row, dict)]
    hashes = [row.get("sha256") for row in views if isinstance(row, dict)]
    if len(hashes) != len(set(hashes)):
        errors.append("admitted view hashes are not unique")
    yaws: list[float] = []
    for row in views:
        if not isinstance(row, dict):
            errors.append("view entry is not an object")
            continue
        if row.get("method") != "source_video_frame":
            errors.append(f"{row.get('view_id')} is not a decoded source frame")
        try:
            image = resolve_under(base, str(row["path"]))
            if not image.is_file():
                errors.append(f"missing view file: {row.get('path')}")
            elif sha256(image) != row.get("sha256"):
                errors.append(f"hash mismatch: {row.get('path')}")
            else:
                actual_image = image_facts(image)
                if actual_image["width"] != row.get("width") or actual_image["height"] != row.get("height"):
                    errors.append(f"dimension mismatch: {row.get('path')}")
            yaws.append(normalize_yaw(float(row["target_yaw_deg"])))
            allowed_yaw_error = float(capture.get("candidate_yaw_radius_deg") or 0.0) + 0.02
            if float(row.get("yaw_error_estimate_deg", 999.0)) > allowed_yaw_error:
                errors.append(f"{row.get('view_id')} yaw error exceeds the admitted candidate radius")
        except (KeyError, TypeError, ValueError, IntakeError) as exc:
            errors.append(f"invalid view {row.get('view_id')}: {exc}")
        candidates = row.get("candidates") if isinstance(row.get("candidates"), list) else []
        if not candidates:
            errors.append(f"{row.get('view_id')} has no recorded candidates")
        for candidate in candidates:
            try:
                candidate_path = resolve_under(base, str(candidate["path"]))
                if not candidate_path.is_file():
                    errors.append(f"missing candidate: {candidate.get('path')}")
                elif sha256(candidate_path) != candidate.get("sha256"):
                    errors.append(f"candidate hash mismatch: {candidate.get('path')}")
            except (KeyError, TypeError, ValueError, IntakeError) as exc:
                errors.append(f"invalid candidate for {row.get('view_id')}: {exc}")
    if len(yaws) >= MIN_ANGLES:
        ordered = sorted(yaws)
        gaps = [
            (ordered[(index + 1) % len(ordered)] - ordered[index]) % 360.0
            for index in range(len(ordered))
        ]
        expected = 360.0 / len(ordered)
        if max(gaps) > expected * 1.25 + 0.02:
            errors.append(f"angular coverage gap {max(gaps):.3f} exceeds allowed {expected * 1.25:.3f}")
    sheet = reference.get("contact_sheet") or {}
    try:
        sheet_path = resolve_under(base, str(sheet["path"]))
        if not sheet_path.is_file() or sha256(sheet_path) != sheet.get("sha256"):
            errors.append("contact-sheet file is missing or changed")
        expected_ids = [row["view_id"] for row in quadrant_review_order(views, error_type=IntakeError)]
        if sheet.get("order") != expected_ids:
            errors.append("contact-sheet order does not match four-quadrant review order")
    except (KeyError, IntakeError) as exc:
        errors.append(f"invalid contact sheet: {exc}")
    primary = reference.get("primary_reference")
    if primary not in {row.get("path") for row in views if isinstance(row, dict)}:
        errors.append("primary_reference is not an admitted view")
    if (reference.get("provenance") or {}).get("synthetic_or_interpolated_views") is not False:
        errors.append("synthetic/interpolated view declaration is not false")
    all_read = review.get("all_views_read_back") or {}
    if all_read.get("status") != "pass":
        errors.append("all_views_read_back is not pass")
    cited_all = set(all_read.get("evidence_views") or [])
    if set(ids) - cited_all:
        errors.append("all_views_read_back does not cite every admitted view")
    gates = review.get("gates") or {}
    for name in REQUIRED_GATES:
        gate = gates.get(name) or {}
        if gate.get("status") != "pass":
            errors.append(f"review gate {name} is not pass")
        evidence = gate.get("evidence_views") or []
        if not evidence:
            errors.append(f"review gate {name} has no evidence views")
        unknown = sorted(set(evidence) - set(ids))
        if unknown:
            errors.append(f"review gate {name} cites unknown views: {', '.join(unknown)}")
    chirality = review.get("chirality") or {}
    for key in ("character_left_profile_view", "character_right_profile_view"):
        if chirality.get(key) not in set(ids):
            errors.append(f"chirality.{key} must cite an admitted view")
    if not review.get("reviewer") or not review.get("reviewed_at"):
        errors.append("reviewer and reviewed_at are required")
    return {
        "schema": REPORT_SCHEMA,
        "checked_at": now_utc(),
        "status": "pass" if not errors else "fail",
        "reference_set": str(reference_path),
        "review": str(review_path),
        "view_count": len(views),
        "errors": errors,
        "warnings": warnings,
    }


def command_verify(args: argparse.Namespace) -> int:
    reference = Path(args.reference_set).expanduser().resolve()
    review = Path(args.review).expanduser().resolve()
    report = verification(reference, review)
    report_path = (
        Path(args.report).expanduser().resolve()
        if args.report
        else reference.parent / "verification-report.json"
    )
    write_json(report_path, report)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "pass" else 2


def resolve_blender(explicit: str | None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    env_path = os.environ.get("BLENDER_EXE")
    if env_path:
        candidates.append(Path(env_path).expanduser())
    discovered = shutil.which("blender")
    if discovered:
        candidates.append(Path(discovered))
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        if resolved.is_file():
            return resolved
    raise IntakeError("Blender executable not found; pass --blender or set BLENDER_EXE")


def command_doctor(args: argparse.Namespace) -> int:
    checks: dict[str, Any] = {}
    errors = []
    for tool in ("ffmpeg", "ffprobe"):
        try:
            checks[tool] = {"status": "pass", "version": tool_version(tool), "path": shutil.which(tool)}
        except IntakeError as exc:
            checks[tool] = {"status": "fail", "error": str(exc)}
            errors.append(str(exc))
    try:
        blender = resolve_blender(args.blender)
        result = run([str(blender), "--version"])
        checks["blender"] = {
            "status": "pass",
            "path": str(blender),
            "version": result.stdout.splitlines()[0].strip(),
            "sha256": sha256(blender),
        }
    except IntakeError as exc:
        checks["blender"] = {"status": "fail", "error": str(exc)}
        errors.append(str(exc))
    payload = {"status": "pass" if not errors else "fail", "checks": checks, "errors": errors}
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if not errors else 2


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Check ffmpeg, ffprobe, and Blender")
    doctor.add_argument("--blender")
    doctor.set_defaults(func=command_doctor)

    probe = sub.add_parser("probe", help="Extract an indexed overview of a video")
    probe.add_argument("video")
    probe.add_argument("--out", required=True)
    probe.add_argument("--frames", type=int, default=64)
    probe.add_argument("--start", type=float, default=0.0)
    probe.add_argument("--end", type=float)
    probe.add_argument("--columns", type=int, default=8)
    probe.set_defaults(func=command_probe)

    build = sub.add_parser("build", help="Build an 8-72 view source-backed reference set")
    build.add_argument("video")
    build.add_argument("--out", required=True)
    build.add_argument("--start", type=float)
    build.add_argument("--end", type=float)
    build.add_argument("--front-time", type=float)
    build.add_argument("--direction", choices=("clockwise", "counterclockwise"))
    build.add_argument("--angles", type=int, default=24)
    build.add_argument("--candidates", type=int, default=1)
    build.add_argument("--candidate-yaw-radius-deg", type=float, default=0.5)
    build.add_argument("--columns", type=int, default=6)
    build.add_argument("--anchors-json")
    build.add_argument("--rotation-audit")
    build.set_defaults(func=command_build)

    verify = sub.add_parser("verify", help="Verify hashes, coverage, and visual review evidence")
    verify.add_argument("--reference-set", required=True)
    verify.add_argument("--review", required=True)
    verify.add_argument("--report")
    verify.set_defaults(func=command_verify)

    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return int(args.func(args))
    except IntakeError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
