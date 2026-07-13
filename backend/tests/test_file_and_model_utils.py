import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app.models.project import Project
from app.utils.file_utils import ensure_inside_any
from app.utils.project_paths import load_project_config, safe_filename_stem


class FileUtilsTests(unittest.TestCase):
    def test_ensure_inside_any_accepts_a_path_in_a_later_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            allowed = base / "allowed"
            allowed.mkdir()

            resolved = ensure_inside_any(allowed / "audio.wav", [base / "other", allowed])

            self.assertEqual(resolved, (allowed / "audio.wav").resolve())

    def test_ensure_inside_any_rejects_path_outside_all_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            with self.assertRaisesRegex(ValueError, "outside allowed project directories"):
                ensure_inside_any(base / "outside.txt", [base / "allowed"])


class ProjectUtilsTests(unittest.TestCase):
    def test_load_project_config_handles_invalid_json(self) -> None:
        project = Project(id="project-1", name="Test", config_json="not-json")
        self.assertEqual(load_project_config(project), {})

    def test_safe_filename_stem_limits_and_sanitizes_names(self) -> None:
        self.assertEqual(safe_filename_stem("  report: demo?  "), "report_demo")
        self.assertLessEqual(len(safe_filename_stem("a" * 100)), 80)

    def test_project_timestamps_are_timezone_aware(self) -> None:
        project = Project(id="project-1", name="Test")
        self.assertIsNotNone(datetime.fromisoformat(project.created_at).tzinfo)


if __name__ == "__main__":
    unittest.main()
