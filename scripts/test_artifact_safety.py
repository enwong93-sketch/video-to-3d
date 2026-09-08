import json
import tempfile
import unittest
from pathlib import Path

from artifact_safety import quadrant_order_manifest, quadrant_review_order, read_json_limited, safe_output_path, validate_image_size, validate_view_ids


class ArtifactSafetyTests(unittest.TestCase):
    def test_rejects_unsafe_or_duplicate_view_ids(self):
        for value in ("../escape", "..\\escape", "C:\\escape", "\\\\server\\share", "view-001:ads", "VIEW-001"):
            with self.assertRaises(ValueError):
                validate_view_ids([{"view_id": value}])
        with self.assertRaises(ValueError):
            validate_view_ids([{"view_id": "view-001"}, {"view_id": "view-001"}])

    def test_output_stays_under_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertEqual(safe_output_path(root, "view-001.png").parent, root.resolve())
            with self.assertRaises(ValueError):
                safe_output_path(root, "../escape.png")

    def test_resource_limits(self):
        self.assertEqual(validate_image_size(1920, 1088, count=24), (1920, 1088))
        with self.assertRaises(ValueError):
            validate_image_size(20000, 20000)

    def test_json_size_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "large.json"
            path.write_text(json.dumps({"x": "a" * (8 * 1024 * 1024)}), encoding="utf-8")
            with self.assertRaises(ValueError):
                read_json_limited(path)

    def test_twenty_four_views_use_quadrant_rounds(self):
        rows = [{"view_id": f"view-{index:03d}", "target_yaw_deg": index * 15.0} for index in range(24)]
        order = [row["target_yaw_deg"] for row in quadrant_review_order(rows)]
        self.assertEqual(order, [
            0.0, 90.0, 180.0, 270.0,
            45.0, 135.0, 225.0, 315.0,
            15.0, 105.0, 195.0, 285.0,
            60.0, 150.0, 240.0, 330.0,
            30.0, 120.0, 210.0, 300.0,
            75.0, 165.0, 255.0, 345.0,
        ])
        self.assertEqual(quadrant_order_manifest(rows)["rounds"][0]["view_ids"], ["view-000", "view-006", "view-012", "view-018"])

    def test_quadrant_rounds_reject_non_divisible_count(self):
        rows = [{"view_id": f"view-{index:03d}", "target_yaw_deg": index * 36.0} for index in range(10)]
        with self.assertRaises(ValueError):
            quadrant_review_order(rows)


if __name__ == "__main__":
    unittest.main()
