import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app.models.project import Project
from app.infrastructure.file_storage import ensure_inside_any
from app.infrastructure.project_layout import (
    get_final_audio_path,
    get_final_srt_path,
    get_final_video_path,
    get_project_work_dir,
    load_project_config,
    safe_filename_stem,
)


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
    def test_selected_output_root_contains_a_project_named_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = Project(
                id="project-1",
                name="人物故事",
                output_dir=str(root / "exports"),
                config_json=(
                    '{"project_directory_name":"人物故事",'
                    '"output_filename":"第一期"}'
                ),
            )

            work_dir = get_project_work_dir(project, root / "workspace")

            self.assertEqual(work_dir, (root / "exports" / "人物故事").resolve())
            self.assertEqual(
                get_final_audio_path(project, root / "workspace"),
                (root / "exports" / "第一期.wav").resolve(),
            )
            self.assertEqual(
                get_final_srt_path(project, root / "workspace"),
                (root / "exports" / "第一期.srt").resolve(),
            )
            self.assertEqual(
                get_final_video_path(project, root / "workspace"),
                (root / "exports" / "第一期.mp4").resolve(),
            )

    def test_project_without_selected_output_keeps_workspace_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            project = Project(id="project-1", name="Test")

            self.assertEqual(
                get_project_work_dir(project, workspace),
                (workspace / "projects" / project.id).resolve(),
            )

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
