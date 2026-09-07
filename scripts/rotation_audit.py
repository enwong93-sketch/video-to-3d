#!/usr/bin/env python3
"""Create or verify an evidence-backed constant-speed turntable audit."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from rotation_contract import AUDIT_SCHEMA, OBSERVATIONS_SCHEMA, sha256, validate_observations


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def extract_frame(video: Path, timestamp: float, destination: Path) -> None:
    if not shutil.which("ffmpeg"):
        raise ValueError("ffmpeg is required")
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
            "-ss", f"{timestamp:.6f}", "-map", "0:v:0", "-an", "-sn", "-dn",
            "-frames:v", "1", str(destination),
        ],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode or not destination.is_file() or destination.stat().st_size == 0:
        raise ValueError(f"could not extract evidence frame at {timestamp:.6f}s: {result.stderr[-1000:]}")


def command_create(args: argparse.Namespace) -> int:
    source = Path(args.video).expanduser().resolve()
    observations_path = Path(args.observations).expanduser().resolve()
    output = Path(args.out).expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"video does not exist: {source}")
    if output.exists():
        raise ValueError(f"audit output already exists: {output}")
    draft = read_json(observations_path)
    if draft.get("schema") != OBSERVATIONS_SCHEMA:
        raise ValueError(f"unsupported observations schema: {draft.get('schema')}")
    draft.setdefault("source", {})
    draft["source"]["path"] = str(source)
    draft["source"]["sha256"] = sha256(source)
    draft.setdefault("limits", {})
    draft["limits"]["max_error_deg"] = args.max_error_deg
    draft["limits"]["rms_error_deg"] = args.rms_error_deg

    evidence_dir = output.parent / f"{output.stem}-evidence"
    if evidence_dir.exists() and any(evidence_dir.iterdir()):
        raise ValueError(f"evidence directory is not empty: {evidence_dir}")
    for index, row in enumerate(draft.get("observations") or []):
        timestamp = float(row["timestamp_seconds"])
        frame = evidence_dir / f"observation-{index:03d}-t{timestamp:010.4f}.png"
        extract_frame(source, timestamp, frame)
        row["evidence"] = {
            "path": str(frame.resolve()),
            "sha256": sha256(frame),
            "kind": "decoded_source_frame",
        }

    report = validate_observations(draft, source_hash=sha256(source))
    payload = {
        "schema": AUDIT_SCHEMA,
        "created_at": now_utc(),
        "status": report["status"],
        "source": draft["source"],
        "turn": report["turn"],
        "limits": report["limits"],
        "metrics": report["metrics"],
        "observations": draft.get("observations") or [],
        "residuals": report["residuals"],
        "errors": report["errors"],
        "observations_file": str(observations_path),
        "observations_file_sha256": sha256(observations_path),
        "evidence_kind": "human_or_agent_angle_observations_backed_by_decoded_source_frames",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "audit": str(output), "metrics": payload["metrics"], "errors": payload["errors"]}, indent=2, ensure_ascii=False))
    return 0 if payload["status"] == "pass" else 2


def verify_payload(audit_path: Path, video: Path | None = None) -> dict[str, Any]:
    audit = read_json(audit_path)
    errors: list[str] = []
    if audit.get("schema") != AUDIT_SCHEMA:
        errors.append(f"unsupported audit schema: {audit.get('schema')}")
    source = audit.get("source") if isinstance(audit.get("source"), dict) else {}
    source_path = video or Path(str(source.get("path", ""))).expanduser().resolve()
    if not source_path.is_file():
        errors.append(f"source video is missing: {source_path}")
        source_hash = None
    else:
        source_hash = sha256(source_path)
        if source_hash != source.get("sha256"):
            errors.append("source video hash mismatch")
    draft = {
        "schema": OBSERVATIONS_SCHEMA,
        "source": source,
        "turn": audit.get("turn"),
        "limits": audit.get("limits"),
        "observations": audit.get("observations"),
    }
    report = validate_observations(draft, source_hash=source_hash)
    errors.extend(report["errors"])
    for index, row in enumerate(audit.get("observations") or []):
        evidence = row.get("evidence") if isinstance(row, dict) else {}
        path = Path(str(evidence.get("path", ""))).expanduser().resolve()
        if not path.is_file():
            errors.append(f"observation {index} evidence is missing")
        elif sha256(path) != evidence.get("sha256"):
            errors.append(f"observation {index} evidence hash mismatch")
    if audit.get("status") != "pass":
        errors.append("stored audit status is not pass")
    if audit.get("metrics") != report["metrics"]:
        errors.append("stored uniformity metrics do not match recomputation")
    return {
        "schema": "video-to-3d-model/rotation-audit-verification/v1",
        "checked_at": now_utc(),
        "status": "pass" if not errors else "fail",
        "audit": str(audit_path),
        "audit_sha256": sha256(audit_path),
        "source": str(source_path),
        "turn": report["turn"],
        "metrics": report["metrics"],
        "errors": errors,
    }


def command_verify(args: argparse.Namespace) -> int:
    audit = Path(args.audit).expanduser().resolve()
    video = Path(args.video).expanduser().resolve() if args.video else None
    report = verify_payload(audit, video)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "pass" else 2


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="Extract evidence frames and calculate constant-speed residuals")
    create.add_argument("--video", required=True)
    create.add_argument("--observations", required=True)
    create.add_argument("--out", required=True)
    create.add_argument("--max-error-deg", type=float, default=2.0)
    create.add_argument("--rms-error-deg", type=float, default=1.0)
    create.set_defaults(func=command_create)
    verify = sub.add_parser("verify", help="Recompute and verify an existing audit")
    verify.add_argument("--audit", required=True)
    verify.add_argument("--video")
    verify.set_defaults(func=command_verify)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return int(args.func(args))
    except ValueError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
