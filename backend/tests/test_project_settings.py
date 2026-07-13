import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.models.project import Project
from app.services import project_service


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    def add(self, _project: Project) -> None:
        pass

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, _project: Project) -> None:
        pass


class ProjectSettingsTests(unittest.TestCase):
    def test_update_project_settings_saves_all_page_fields_together(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_dir = root / "output"
            video_dir = root / "videos"
            workspace_dir = root / "workspace"
            video_dir.mkdir()
            project = Project(id="project-id", name="Old name", config_json="{}")
            session = FakeSession()

            with patch.object(
                project_service,
                "get_settings",
                return_value=SimpleNamespace(workspace_dir=workspace_dir),
            ):
                result = project_service.update_project_settings(
                    session,
                    project,
                    "  New name  ",
                    str(output_dir),
                    "voice file",
                    str(video_dir),
                )

            config = json.loads(result.config_json or "{}")
            self.assertEqual(result.name, "New name")
            self.assertEqual(result.output_dir, str(output_dir.resolve()))
            self.assertEqual(config["output_filename"], "voice_file")
            self.assertEqual(config["media_video_dir"], str(video_dir.resolve()))
            self.assertEqual(session.commits, 1)

    def test_update_project_settings_validates_before_mutating_project(self) -> None:
        project = Project(id="project-id", name="Old name", config_json="{}")

        with self.assertRaisesRegex(ValueError, "Video material directory does not exist"):
            project_service.update_project_settings(
                FakeSession(),
                project,
                "New name",
                "unused-output",
                "voice",
                "missing-video-directory",
            )

        self.assertEqual(project.name, "Old name")
        self.assertIsNone(project.output_dir)


if __name__ == "__main__":
    unittest.main()
