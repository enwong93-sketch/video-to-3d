import json
import tempfile
import unittest
from pathlib import Path

from artifact_safety import read_json_limited, safe_output_path, validate_image_size, validate_view_ids


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


if __name__ == "__main__":
    unittest.main()
