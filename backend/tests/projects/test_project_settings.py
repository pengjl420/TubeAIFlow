import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

from app.models.project import Project
from app.models.narration import Segment
from app.models.task import TaskRun
from app.services.projects import project_service


class FakeSession:
    def __init__(self, segments: list[Segment] | None = None) -> None:
        self.commits = 0
        self.segments = segments or []

    def add(self, _project: Project) -> None:
        pass

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, _project: Project) -> None:
        pass

    def exec(self, _statement):
        return SimpleNamespace(all=lambda: self.segments)


class ProjectSettingsTests(unittest.TestCase):
    def test_project_response_exposes_typed_config(self) -> None:
        project = Project(
            id="project-id",
            name="Name",
            config_json='{"reference_audio_filename": "narrator.wav"}',
        )

        response = project_service.project_response(project)

        self.assertEqual(response["config"]["reference_audio_filename"], "narrator.wav")
        self.assertEqual(response["config_json"], project.config_json)

    def test_project_metrics_use_audio_durations_and_actual_task_start(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(f"sqlite:///{Path(directory) / 'metrics.db'}")
            SQLModel.metadata.create_all(engine)
            with Session(engine) as session:
                session.add(Project(
                    id="project-id",
                    name="Name",
                    created_at="2026-07-17T01:00:00+00:00",
                ))
                session.add(Segment(
                    id="segment-1", segment_id="0001", project_id="project-id",
                    segment_index=1, text="第一段", duration=61.25,
                ))
                session.add(Segment(
                    id="segment-2", segment_id="0002", project_id="project-id",
                    segment_index=2, text="第二段", duration=2.5,
                ))
                session.add(TaskRun(
                    id="task-id", project_id="project-id", queue_sequence=1,
                    status="completed",
                    created_at="2026-07-17T02:00:00+00:00",
                    started_at="2026-07-17T03:00:00+00:00",
                    finished_at="2026-07-17T03:01:30+00:00",
                ))
                session.commit()

                response = project_service.list_projects(session)[0]

            self.assertEqual(response["audio_duration_seconds"], 63.75)
            self.assertEqual(response["workflow_started_at"], "2026-07-17T03:00:00+00:00")
            self.assertEqual(response["workflow_duration_seconds"], 90.0)
            self.assertNotEqual(response["created_at"], response["workflow_started_at"])
            engine.dispose()

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
            self.assertEqual(config["project_directory_name"], "New_name")
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

    def test_video_directory_is_required_only_when_video_is_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = Project(id="project-id", name="Name", config_json="{}")

            with patch.object(
                project_service,
                "get_settings",
                return_value=SimpleNamespace(workspace_dir=root / "workspace"),
            ):
                with self.assertRaisesRegex(ValueError, "Video material directory is required"):
                    project_service.update_project_settings(
                        FakeSession(),
                        project,
                        "Name",
                        str(root / "output"),
                        "voice",
                        "",
                        include_video=True,
                    )

                result = project_service.update_project_settings(
                    FakeSession(),
                    project,
                    "Name",
                    str(root / "output"),
                    "voice",
                    "",
                    include_video=False,
                )

            config = json.loads(result.config_json or "{}")
            self.assertFalse(config["include_video"])

    def test_ai_semantic_video_does_not_require_landscape_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = Project(id="project-id", name="Name", config_json="{}")
            with patch.object(
                project_service,
                "get_settings",
                return_value=SimpleNamespace(workspace_dir=root / "workspace"),
            ):
                result = project_service.update_project_settings(
                    FakeSession(),
                    project,
                    "Name",
                    str(root / "output"),
                    "voice",
                    "",
                    include_video=True,
                    video_mode="ai_semantic",
                )

            config = json.loads(result.config_json or "{}")
            self.assertTrue(config["include_video"])
            self.assertEqual(config["video_mode"], "ai_semantic")
            self.assertNotIn("media_video_dir", config)

    def test_legacy_include_video_projects_resolve_to_landscape_mode(self) -> None:
        project = Project(
            id="project-id",
            name="Name",
            config_json='{"include_video":true}',
        )
        self.assertEqual(
            project_service.get_project_video_mode(project),
            project_service.VIDEO_MODE_LANDSCAPE,
        )

    def test_semantic_review_mode_defaults_to_manual_and_persists_automatic(self) -> None:
        legacy = Project(id="legacy", name="Legacy", config_json="{}")
        self.assertEqual(
            project_service.get_semantic_review_mode(legacy),
            project_service.SEMANTIC_REVIEW_MANUAL,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = Project(id="project-id", name="Name", config_json="{}")
            with patch.object(
                project_service,
                "get_settings",
                return_value=SimpleNamespace(workspace_dir=root / "workspace"),
            ):
                result = project_service.update_project_settings(
                    FakeSession(),
                    project,
                    "Name",
                    str(root / "output"),
                    "voice",
                    "",
                    include_video=True,
                    video_mode="ai_semantic",
                    semantic_review_mode="automatic",
                )
        self.assertEqual(
            json.loads(result.config_json or "{}")["semantic_review_mode"],
            "automatic",
        )

    def test_switching_to_qwen_resets_completed_segments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            segment = Segment(
                id="project-id_0001",
                project_id="project-id",
                segment_id="0001",
                segment_index=1,
                text="测试",
                status="completed",
                audio_path="old.wav",
                duration=1.2,
            )
            project = Project(
                id="project-id",
                name="Name",
                status="tts_completed",
                config_json='{"tts_engine": "chatterbox"}',
            )
            session = FakeSession([segment])

            with patch.object(
                project_service,
                "get_settings",
                return_value=SimpleNamespace(workspace_dir=root / "workspace"),
            ):
                result = project_service.update_project_settings(
                    session,
                    project,
                    "Name",
                    str(root / "output"),
                    "voice",
                    "",
                    "qwen3_tts",
                    "参考文本",
                )

            config = json.loads(result.config_json or "{}")
            self.assertEqual(config["tts_engine"], "qwen3_tts")
            self.assertEqual(config["reference_audio_text"], "参考文本")
            self.assertEqual(result.status, "segmented")
            self.assertEqual(segment.status, "pending")
            self.assertIsNone(segment.audio_path)
            self.assertIsNone(segment.duration)


if __name__ == "__main__":
    unittest.main()
