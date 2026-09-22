import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine, select

from app.models.project import Project
from app.models.narration import Segment
from app.models.media import (
    GeneratedImageVariant,
    MediaFile,
    MediaShot,
    SceneAssignment,
    SceneCandidate,
)
from app.models.storyboard import SceneRevision, SubtitleCue, VisualScene
from app.models.task import TaskRun
from app.infrastructure.project_layout import (
    get_final_audio_path,
    get_final_srt_path,
    get_final_video_path,
    get_project_work_dir,
)
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
    def test_script_change_invalidates_every_downstream_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = SimpleNamespace(workspace_dir=root / "workspace")
            project = Project(
                id="project-id",
                name="Project",
                output_dir=str(root / "output"),
                status="completed",
                config_json=json.dumps(
                    {"output_filename": "project", "project_directory_name": "project-work"}
                ),
            )
            engine = create_engine("sqlite://")
            SQLModel.metadata.create_all(engine)
            with (
                Session(engine) as session,
                patch.object(project_service, "get_settings", return_value=settings),
            ):
                session.add(project)
                project_service.save_script(session, project, "old script")
                session.add(
                    Segment(
                        id="segment",
                        segment_id="0001",
                        project_id=project.id,
                        segment_index=1,
                        text="old script",
                        status="completed",
                    )
                )
                session.add(
                    SubtitleCue(
                        id="cue",
                        project_id=project.id,
                        source_segment_id="segment",
                        cue_index=1,
                        start_ms=0,
                        end_ms=1_000,
                        text="old script",
                    )
                )
                session.add(
                    VisualScene(
                        id="scene",
                        project_id=project.id,
                        scene_index=1,
                        start_ms=0,
                        end_ms=1_000,
                        narration="old script",
                    )
                )
                session.add(
                    SceneRevision(
                        id="revision",
                        project_id=project.id,
                        scene_id="scene",
                        version=1,
                        snapshot_json="{}",
                    )
                )
                session.add(
                    MediaFile(
                        id="media",
                        provider="local_image_generation",
                        path="old.png",
                        filename="old.png",
                        media_type="image",
                        file_hash="hash",
                    )
                )
                session.add(MediaShot(id="shot", media_file_id="media", shot_index=1))
                session.add(
                    GeneratedImageVariant(
                        id="variant",
                        project_id=project.id,
                        scene_id="scene",
                        variant_index=1,
                        path="old.png",
                        prompt="old",
                        model_path="model",
                        input_signature="sig",
                        seed=1,
                        width=16,
                        height=9,
                        steps=1,
                        guidance_scale=1,
                        media_file_id="media",
                    )
                )
                session.add(
                    SceneAssignment(
                        id="assignment",
                        project_id=project.id,
                        scene_id="scene",
                        media_shot_id="shot",
                    )
                )
                session.add(
                    SceneCandidate(
                        id="candidate",
                        project_id=project.id,
                        scene_id="scene",
                        media_shot_id="shot",
                    )
                )
                session.commit()

                final_paths = (
                    get_final_audio_path(project, settings.workspace_dir),
                    get_final_srt_path(project, settings.workspace_dir),
                    get_final_video_path(project, settings.workspace_dir),
                )
                work_file = (
                    get_project_work_dir(project, settings.workspace_dir)
                    / "timeline"
                    / "timeline.json"
                )
                for path in (*final_paths, work_file):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("stale", encoding="utf-8")

                project_service.save_script(session, project, "new script")

                self.assertEqual(project.status, "script_imported")
                self.assertEqual(session.exec(select(Segment)).all(), [])
                self.assertEqual(session.exec(select(SubtitleCue)).all(), [])
                self.assertEqual(session.exec(select(VisualScene)).all(), [])
                self.assertEqual(session.exec(select(SceneRevision)).all(), [])
                self.assertEqual(session.exec(select(SceneAssignment)).all(), [])
                self.assertEqual(session.exec(select(SceneCandidate)).all(), [])
                self.assertEqual(session.exec(select(GeneratedImageVariant)).all(), [])
                self.assertIsNone(session.get(MediaFile, "media"))
                self.assertTrue(all(not path.exists() for path in (*final_paths, work_file)))

            engine.dispose()

    def test_saving_identical_script_preserves_completed_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = SimpleNamespace(workspace_dir=root / "workspace")
            project = Project(
                id="project-id",
                name="Project",
                output_dir=str(root / "output"),
                config_json=json.dumps(
                    {"output_filename": "project", "project_directory_name": "project-work"}
                ),
            )
            engine = create_engine("sqlite://")
            SQLModel.metadata.create_all(engine)
            with (
                Session(engine) as session,
                patch.object(project_service, "get_settings", return_value=settings),
            ):
                session.add(project)
                project_service.save_script(session, project, "same script")
                project.status = "completed"
                session.add(
                    Segment(
                        id="segment",
                        segment_id="0001",
                        project_id=project.id,
                        segment_index=1,
                        text="same script",
                        status="completed",
                    )
                )
                session.commit()

                project_service.save_script(session, project, "same script")

                self.assertEqual(project.status, "completed")
                self.assertIsNotNone(session.get(Segment, "segment"))

            engine.dispose()

    def test_script_change_rejects_locked_scenes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = SimpleNamespace(workspace_dir=root / "workspace")
            project = Project(id="project-id", name="Project", config_json="{}")
            engine = create_engine("sqlite://")
            SQLModel.metadata.create_all(engine)
            with (
                Session(engine) as session,
                patch.object(project_service, "get_settings", return_value=settings),
            ):
                session.add(project)
                project_service.save_script(session, project, "old script")
                session.add(
                    VisualScene(
                        id="scene",
                        project_id=project.id,
                        scene_index=1,
                        start_ms=0,
                        end_ms=1_000,
                        narration="old script",
                        locked_text=True,
                    )
                )
                session.commit()

                with self.assertRaisesRegex(ValueError, "Scene 1 is locked"):
                    project_service.save_script(session, project, "new script")

                self.assertEqual(
                    Path(project.script_raw_path or "").read_text(encoding="utf-8"),
                    "old script",
                )
                self.assertIsNotNone(session.get(VisualScene, "scene"))

            engine.dispose()

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
                session.add(
                    Project(
                        id="project-id",
                        name="Name",
                        created_at="2026-07-17T01:00:00+00:00",
                    )
                )
                session.add(
                    Segment(
                        id="segment-1",
                        segment_id="0001",
                        project_id="project-id",
                        segment_index=1,
                        text="第一段",
                        duration=61.25,
                    )
                )
                session.add(
                    Segment(
                        id="segment-2",
                        segment_id="0002",
                        project_id="project-id",
                        segment_index=2,
                        text="第二段",
                        duration=2.5,
                    )
                )
                session.add(
                    TaskRun(
                        id="task-id",
                        project_id="project-id",
                        queue_sequence=1,
                        status="completed",
                        created_at="2026-07-17T02:00:00+00:00",
                        started_at="2026-07-17T03:00:00+00:00",
                        finished_at="2026-07-17T03:01:30+00:00",
                    )
                )
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
            self.assertTrue(config["storyboard_transition_enabled"])
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

    def test_generated_image_video_does_not_require_landscape_directory(self) -> None:
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
                    video_mode="ai_generated_images",
                )

            config = json.loads(result.config_json or "{}")
            self.assertTrue(config["include_video"])
            self.assertEqual(config["video_mode"], "ai_generated_images")
            self.assertNotIn("media_video_dir", config)

    def test_video_settings_can_be_enabled_without_invalidating_narration(self) -> None:
        project = Project(
            id="project-id",
            name="Narration ready",
            status="narration_ready",
            config_json='{"include_video":false,"tts_engine":"qwen3_tts"}',
        )

        result = project_service.update_video_workflow_settings(
            FakeSession(),
            project,
            video_mode="ai_generated_images",
        )

        config = json.loads(result.config_json or "{}")
        self.assertEqual(result.status, "narration_ready")
        self.assertEqual(config["tts_engine"], "qwen3_tts")
        self.assertTrue(config["include_video"])
        self.assertEqual(config["video_mode"], "ai_generated_images")

    def test_anime_generation_mode_is_limited_to_full_ai_image_projects(self) -> None:
        project = Project(
            id="project-id",
            name="Narration ready",
            status="narration_ready",
            config_json='{"include_video":false}',
        )

        anime = project_service.update_video_workflow_settings(
            FakeSession(),
            project,
            video_mode="ai_generated_images",
            visual_generation_mode="anime_full_coverage",
        )
        self.assertEqual(
            json.loads(anime.config_json)["visual_generation_mode"],
            "anime_full_coverage",
        )

        with self.assertRaisesRegex(ValueError, "incompatible"):
            project_service.update_video_workflow_settings(
                FakeSession(),
                project,
                video_mode="ai_landscape_mix",
                media_video_dir=".",
                visual_generation_mode="anime_full_coverage",
            )

    def test_visual_generation_mode_change_invalidates_existing_assignments(self) -> None:
        from app.workflows.video_synthesis import initial_stage

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = SimpleNamespace(workspace_dir=root / "workspace")
            project = Project(
                id="project-id",
                name="Completed project",
                output_dir=str(root / "output"),
                status="completed",
                config_json=json.dumps(
                    {
                        "include_video": True,
                        "video_mode": "ai_generated_images",
                        "storyboard_mode": "ai",
                        "visual_enrichment_mode": "auto",
                        "visual_generation_mode": "curated",
                    }
                ),
            )
            scene = VisualScene(
                id="scene-id",
                project_id=project.id,
                scene_index=1,
                start_ms=0,
                end_ms=8_000,
                narration="Narration",
                storyboard_json=json.dumps({"visual_summary": "Existing storyboard"}),
            )
            assignment = SceneAssignment(
                id="assignment-id",
                project_id=project.id,
                scene_id=scene.id,
                media_shot_id="shot-id",
                scene_offset_start_ms=0,
                scene_offset_end_ms=8_000,
            )
            variant = GeneratedImageVariant(
                id="old-advanced-variant",
                project_id=project.id,
                scene_id=scene.id,
                variant_index=0,
                path=str(root / "old.png"),
                prompt="old curated prompt",
                model_path="flux",
                input_signature="old-signature",
                seed=1,
                width=1344,
                height=768,
                steps=0,
                guidance_scale=0,
                status="completed",
                workflow_version="advanced_visual_pipeline_v1",
            )
            locked_scene = VisualScene(
                id="locked-scene-id",
                project_id=project.id,
                scene_index=2,
                start_ms=8_000,
                end_ms=16_000,
                narration="Locked narration",
                storyboard_json=json.dumps({"visual_summary": "Locked storyboard"}),
                locked_visual=True,
            )
            locked_assignment = SceneAssignment(
                id="locked-assignment-id",
                project_id=project.id,
                scene_id=locked_scene.id,
                media_shot_id="locked-shot-id",
                scene_offset_start_ms=0,
                scene_offset_end_ms=8_000,
            )
            locked_variant = GeneratedImageVariant(
                id="locked-advanced-variant",
                project_id=project.id,
                scene_id=locked_scene.id,
                variant_index=0,
                path=str(root / "locked.png"),
                prompt="locked prompt",
                model_path="flux",
                input_signature="locked-signature",
                seed=2,
                width=1344,
                height=768,
                steps=0,
                guidance_scale=0,
                status="completed",
                workflow_version="advanced_visual_pipeline_v1",
            )
            engine = create_engine("sqlite://")
            SQLModel.metadata.create_all(engine)
            with Session(engine) as session, patch.object(
                project_service, "get_settings", return_value=settings
            ), patch.object(project_service, "write_project_descriptor"):
                session.add_all([
                    project,
                    scene,
                    assignment,
                    variant,
                    locked_scene,
                    locked_assignment,
                    locked_variant,
                ])
                session.commit()

                project_service.update_video_workflow_settings(
                    session,
                    project,
                    video_mode="ai_generated_images",
                    storyboard_mode="ai",
                    visual_enrichment_mode="auto",
                    visual_generation_mode="anime_full_coverage",
                )

                remaining_assignments = session.exec(select(SceneAssignment)).all()
                self.assertEqual([item.id for item in remaining_assignments], [locked_assignment.id])
                session.refresh(variant)
                self.assertEqual(variant.status, "stale")
                session.refresh(locked_variant)
                self.assertEqual(locked_variant.status, "completed")
                self.assertEqual(initial_stage(session, project.id), "image_generation")
            engine.dispose()

    def test_video_setting_change_invalidates_only_downstream_video_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = SimpleNamespace(workspace_dir=root / "workspace")
            project = Project(
                id="project-id",
                name="Project",
                output_dir=str(root / "output"),
                status="completed",
                config_json=json.dumps(
                    {
                        "output_filename": "project",
                        "project_directory_name": "project-work",
                        "include_video": True,
                        "video_mode": "ai_generated_images",
                        "storyboard_mode": "ai",
                    }
                ),
            )
            scene = VisualScene(
                id="scene-id",
                project_id=project.id,
                scene_index=1,
                start_ms=0,
                end_ms=1_000,
                narration="Narration",
                storyboard_json='{"visual_summary":"old"}',
            )
            engine = create_engine("sqlite://")
            SQLModel.metadata.create_all(engine)
            with Session(engine) as session:
                session.add(project)
                session.add(scene)
                session.add(
                    SceneAssignment(
                        id="assignment",
                        project_id=project.id,
                        scene_id=scene.id,
                        media_shot_id="shot",
                    )
                )
                session.add(
                    SceneCandidate(
                        id="candidate",
                        project_id=project.id,
                        scene_id=scene.id,
                        media_shot_id="shot",
                    )
                )
                session.commit()

                audio_path = get_final_audio_path(project, settings.workspace_dir)
                subtitle_path = get_final_srt_path(project, settings.workspace_dir)
                video_path = get_final_video_path(project, settings.workspace_dir)
                work_dir = get_project_work_dir(project, settings.workspace_dir)
                for path in (
                    audio_path,
                    subtitle_path,
                    video_path,
                    work_dir / "renders" / "visual_track.mp4",
                    work_dir / "reports" / "quality_report.json",
                    work_dir / "timeline" / "timeline.json",
                ):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"artifact")

                with (
                    patch.object(project_service, "get_settings", return_value=settings),
                    patch.object(project_service, "write_project_descriptor"),
                ):
                    result = project_service.update_video_workflow_settings(
                        session,
                        project,
                        video_mode="ai_generated_images",
                        storyboard_mode="segments",
                    )

                self.assertEqual(result.status, "narration_ready")
                self.assertTrue(audio_path.is_file())
                self.assertTrue(subtitle_path.is_file())
                self.assertFalse(video_path.exists())
                self.assertFalse((work_dir / "renders" / "visual_track.mp4").exists())
                self.assertFalse((work_dir / "reports" / "quality_report.json").exists())
                self.assertFalse((work_dir / "timeline" / "timeline.json").exists())
                self.assertEqual(len(session.exec(select(SceneAssignment)).all()), 0)
                self.assertEqual(len(session.exec(select(SceneCandidate)).all()), 0)
                self.assertIsNone(session.get(VisualScene, scene.id).storyboard_json)
            engine.dispose()

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

    def test_output_defaults_to_prproj(self) -> None:
        legacy = Project(id="legacy", name="Legacy", config_json="{}")
        self.assertEqual(
            project_service.normalize_video_output_format(None),
            project_service.VIDEO_OUTPUT_PRPROJ,
        )
        self.assertEqual(
            project_service.get_video_output_format(legacy),
            project_service.VIDEO_OUTPUT_PRPROJ,
        )

    def test_storyboard_defaults_to_semantic_grouping(self) -> None:
        legacy = Project(id="legacy", name="Legacy", config_json="{}")
        self.assertEqual(
            project_service.normalize_storyboard_mode(None),
            project_service.STORYBOARD_MODE_AI,
        )
        self.assertEqual(
            project_service.get_storyboard_mode(legacy),
            project_service.STORYBOARD_MODE_AI,
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
                config_json='{"tts_engine": "cosyvoice"}',
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
