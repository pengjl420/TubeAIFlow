import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

from app.models.media import MediaFile, MediaShot, SceneAssignment
from app.models.project import Project
from app.models.storyboard import SubtitleCue, VisualScene
from app.services.quality import qa_service
from app.services.rendering import scene_renderer
from app.workflows import video_synthesis


class IntelligentVideoPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.engine = create_engine(
            f"sqlite:///{self.root / 'pipeline.db'}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temp.cleanup()

    def test_asset_search_stops_at_manual_review_gate(self) -> None:
        with Session(self.engine) as session:
            project, scene = self._project_with_scene(session)
            changed = []
            with (
                patch.object(video_synthesis, "_ingest_configured_assets"),
                patch.object(video_synthesis.retrieval_service, "search_scene_candidates") as search,
            ):
                with self.assertRaises(video_synthesis.ReviewRequired) as raised:
                    video_synthesis.run_video_synthesis(
                        session, project, "asset_search", changed.append
                    )

            self.assertEqual(raised.exception.stage, "asset_review")
            self.assertEqual(changed, ["asset_review"])
            search.assert_called_once_with(session, project, scene.id)

    def test_confirmed_assignments_continue_through_qa(self) -> None:
        with Session(self.engine) as session:
            project, scene = self._project_with_scene(session)
            media_file, shot = self._media(session)
            session.add(
                SceneAssignment(
                    id="assignment-1",
                    project_id=project.id,
                    scene_id=scene.id,
                    media_shot_id=shot.id,
                    manual_confirmed=True,
                )
            )
            session.commit()
            changed = []
            with (
                patch.object(video_synthesis.scene_renderer, "render_all_scenes") as render_scenes,
                patch.object(video_synthesis.final_renderer, "compose_final_video") as render_final,
                patch.object(
                    video_synthesis.qa_service,
                    "run_quality_check",
                    return_value={"passed": True, "summary": {"error_count": 0}},
                ) as qa,
            ):
                video_synthesis.run_video_synthesis(
                    session, project, "asset_review", changed.append
                )

            self.assertEqual(
                changed,
                ["scene_render", "final_render", "quality_check", "completed"],
            )
            render_scenes.assert_called_once_with(session, project)
            render_final.assert_called_once_with(session, project)
            qa.assert_called_once_with(session, project)
            self.assertEqual(media_file.id, "media-1")

    def test_scene_renderer_is_resumable_for_unchanged_assignment(self) -> None:
        source = self.root / "source.mp4"
        source.write_bytes(b"video")
        with Session(self.engine) as session:
            project, scene = self._project_with_scene(session)
            _, shot = self._media(session, source)
            assignment = SceneAssignment(
                id="assignment-1",
                project_id=project.id,
                scene_id=scene.id,
                media_shot_id=shot.id,
                manual_confirmed=True,
            )
            session.add(assignment)
            session.commit()
            settings = SimpleNamespace(workspace_dir=self.root)

            def fake_ffmpeg(args, _project_id):
                Path(args[-1]).write_bytes(b"mp4")

            with (
                patch.object(scene_renderer, "get_settings", return_value=settings),
                patch.object(scene_renderer, "run_ffmpeg", side_effect=fake_ffmpeg) as ffmpeg,
                patch.object(scene_renderer, "probe_duration", return_value=5.0),
            ):
                first = scene_renderer.render_scene(session, project, scene, assignment)
                second = scene_renderer.render_scene(session, project, scene, assignment)

            self.assertFalse(first["skipped"])
            self.assertTrue(second["skipped"])
            self.assertEqual(ffmpeg.call_count, 1)
            args = ffmpeg.call_args.args[0]
            self.assertEqual(args[args.index("-c:v") + 1], "libx264")
            self.assertIn("1920:1080", args[args.index("-filter_complex") + 1])

    def test_qa_report_passes_for_continuous_complete_timeline(self) -> None:
        source = self.root / "source.mp4"
        source.write_bytes(b"video")
        with Session(self.engine) as session:
            project, scene = self._project_with_scene(session)
            _, shot = self._media(session, source)
            session.add(
                SceneAssignment(
                    id="assignment-1",
                    project_id=project.id,
                    scene_id=scene.id,
                    media_shot_id=shot.id,
                    manual_confirmed=True,
                )
            )
            session.add(
                SubtitleCue(
                    id="cue-1",
                    project_id=project.id,
                    source_segment_id="segment-1",
                    cue_index=1,
                    start_ms=0,
                    end_ms=5000,
                    text="测试字幕",
                )
            )
            session.commit()
            settings = SimpleNamespace(workspace_dir=self.root)
            audio = self.root / "Project.wav"
            video = self.root / "Project.mp4"
            subtitle = self.root / "Project.srt"
            for path in (audio, video, subtitle):
                path.write_bytes(b"data")
            scene_path = (
                self.root / "projects" / project.id / "renders" / "scenes" / "scene_0001.mp4"
            )
            scene_path.parent.mkdir(parents=True, exist_ok=True)
            scene_path.write_bytes(b"scene")

            with (
                patch.object(qa_service, "get_settings", return_value=settings),
                patch.object(scene_renderer, "get_settings", return_value=settings),
                patch.object(qa_service, "probe_duration", return_value=5.0),
                patch.object(
                    qa_service,
                    "probe_media",
                    return_value={"width": 1920, "height": 1080, "codec_name": "h264"},
                ),
            ):
                report = qa_service.run_quality_check(session, project)

            self.assertTrue(report["passed"])
            self.assertEqual(report["issues"], [])
            self.assertTrue((self.root / "projects" / project.id / "reports" / "qa.json").is_file())

    def _project_with_scene(self, session: Session) -> tuple[Project, VisualScene]:
        project = Project(id="project-1", name="Project", output_dir=str(self.root))
        scene = VisualScene(
            id="scene-1",
            project_id=project.id,
            scene_index=1,
            start_ms=0,
            end_ms=5000,
            narration="测试旁白",
        )
        session.add_all([project, scene])
        session.commit()
        return project, scene

    def _media(
        self, session: Session, source: Path | None = None
    ) -> tuple[MediaFile, MediaShot]:
        source = source or (self.root / "media.mp4")
        if not source.exists():
            source.write_bytes(b"video")
        media_file = MediaFile(
            id="media-1",
            path=str(source),
            filename=source.name,
            media_type="video",
            file_hash="hash-1",
            duration_ms=5000,
            width=1920,
            height=1080,
        )
        shot = MediaShot(
            id="shot-1",
            media_file_id=media_file.id,
            shot_index=1,
            start_ms=0,
            end_ms=5000,
        )
        session.add_all([media_file, shot])
        session.commit()
        return media_file, shot


if __name__ == "__main__":
    unittest.main()
