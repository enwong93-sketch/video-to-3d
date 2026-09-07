#!/usr/bin/env python3
"""Deterministic unit checks for turntable_reference.py."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("turntable_reference.py")
SPEC = importlib.util.spec_from_file_location("turntable_reference", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TurntableReferenceTests(unittest.TestCase):
    def test_default_uniform_targets_cover_24_angles(self) -> None:
        rows = MODULE.uniform_targets(24, 1.0, 13.0, 2.0, "clockwise")
        self.assertEqual(len(rows), 24)
        self.assertEqual([row["yaw_deg"] for row in rows], [index * 15.0 for index in range(24)])
        self.assertTrue(all(1.0 <= row["timestamp_seconds"] < 13.0 for row in rows))

    def test_counterclockwise_still_sorts_canonical_yaw(self) -> None:
        rows = MODULE.uniform_targets(16, 0.0, 8.0, 1.0, "counterclockwise")
        self.assertEqual([row["yaw_deg"] for row in rows], [index * 22.5 for index in range(16)])

    def test_candidate_offsets_are_bounded_and_centered(self) -> None:
        offsets = MODULE.candidate_offsets(5, 1.0, 0.05)
        self.assertEqual(offsets[2], 0.0)
        self.assertAlmostEqual(offsets[0], -0.05)
        self.assertAlmostEqual(offsets[-1], 0.05)

    def test_supported_angle_range_is_8_to_72(self) -> None:
        self.assertEqual(MODULE.MIN_ANGLES, 8)
        self.assertEqual(MODULE.MAX_ANGLES, 72)

    def test_anchor_contract_rejects_missing_angles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "anchors.json"
            path.write_text(json.dumps([{"yaw_deg": 0, "timestamp_seconds": 1}]), encoding="utf-8")
            with self.assertRaises(MODULE.IntakeError):
                MODULE.load_anchors(path, 16, 0.0, 10.0)

    def test_resolve_under_rejects_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(MODULE.IntakeError):
                MODULE.resolve_under(Path(temp_dir), "../escape.png")


if __name__ == "__main__":
    unittest.main()
