#!/usr/bin/env python3
"""Deterministic checks for the rotation evidence contract."""

from __future__ import annotations

import unittest

import rotation_contract as contract


def observations(timestamps: list[float]) -> dict:
    degrees = [0, 45, 90, 135, 180, 225, 270, 315, 360]
    return {
        "schema": contract.OBSERVATIONS_SCHEMA,
        "source": {"sha256": "abc"},
        "turn": {
            "start_seconds": 0.0,
            "end_seconds": 8.0,
            "front_time_seconds": 0.0,
            "direction": "clockwise",
        },
        "limits": {"max_error_deg": 2.0, "rms_error_deg": 1.0},
        "observations": [
            {
                "turn_deg": degree,
                "timestamp_seconds": timestamp,
                "evidence": {"path": f"frame-{index}.png", "sha256": f"hash-{index}"},
            }
            for index, (degree, timestamp) in enumerate(zip(degrees, timestamps))
        ],
    }


class RotationContractTests(unittest.TestCase):
    def test_uniform_observations_pass(self) -> None:
        report = contract.validate_observations(observations([0, 1, 2, 3, 4, 5, 6, 7, 8]), "abc")
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["metrics"]["observed_orientation_bands"], 8)
        self.assertEqual(report["metrics"]["max_error_deg"], 0.0)

    def test_non_uniform_motion_fails_closed(self) -> None:
        report = contract.validate_observations(observations([0, 1, 2, 3.2, 4, 5, 6, 7, 8]), "abc")
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("residual" in error for error in report["errors"]))

    def test_source_hash_mismatch_fails(self) -> None:
        report = contract.validate_observations(observations([0, 1, 2, 3, 4, 5, 6, 7, 8]), "different")
        self.assertEqual(report["status"], "fail")
        self.assertIn("source video hash does not match observations", report["errors"])


if __name__ == "__main__":
    unittest.main()
