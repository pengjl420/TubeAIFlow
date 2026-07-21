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
from app.services.rendering import scene_renderer, timeline_composer
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

    def test_asset_search_auto_review_selects_candidates_before_review_gate(self) -> None:
        with Session(self.engine) as session:
            project, scene = self._project_with_scene(session)
            project.config_json = '{"video_mode":"ai_semantic","semantic_review_mode":"automatic"}'
            session.add(project)
            session.commit()
            changed = []
            with (
                patch.object(video_synthesis, "_ingest_configured_assets"),
                patch.object(video_synthesis.retrieval_service, "search_scene_candidates"),
                patch.object(
                    video_synthesis.retrieval_service,
                    "auto_assign_qualified_candidates",
                ) as auto_assign,
            ):
                with self.assertRaises(video_synthesis.ReviewRequired):
                    video_synthesis.run_video_synthesis(
                        session, project, "asset_search", changed.append
                    )

            auto_assign.assert_called_once_with(session, project, scene.id)
            self.assertEqual(changed, ["asset_review"])

    def test_generated_image_mode_uses_image_generation_review_gate(self) -> None:
        with Session(self.engine) as session:
            project, _scene = self._project_with_scene(session)
            project.config_json = '{"video_mode":"ai_generated_images","semantic_review_mode":"manual"}'
            session.add(project)
            session.commit()
            changed = []
            with (
                patch.object(
                    video_synthesis.image_generation_service,
                    "generate_project_images",
                ) as generate,
                patch.object(
                    video_synthesis.image_selection_service,
                    "score_project_images",
                ) as score,
            ):
                with self.assertRaises(video_synthesis.ReviewRequired) as raised:
                    video_synthesis.run_video_synthesis(
                        session, project, "image_generation", changed.append
                    )

            generate.assert_called_once_with(session, project)
            score.assert_called_once_with(session, project)
            self.assertEqual(raised.exception.stage, "image_review")
            self.assertEqual(changed, ["image_review"])

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
                patch.object(
                    video_synthesis.visual_track_composer,
                    "compose_visual_track",
                ) as compose_visual_track,
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
                ["scene_render", "visual_track", "final_render", "quality_check", "completed"],
            )
            render_scenes.assert_called_once_with(session, project)
            compose_visual_track.assert_called_once_with(session, project)
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
                patch.object(
                    scene_renderer,
                    "check_scene_video",
                    return_value=self._quality(5.0),
                ),
            ):
                first = scene_renderer.render_scene(session, project, scene, assignment)
                second = scene_renderer.render_scene(session, project, scene, assignment)

            self.assertFalse(first["skipped"])
            self.assertTrue(second["skipped"])
            self.assertEqual(ffmpeg.call_count, 1)
            args = ffmpeg.call_args.args[0]
            self.assertEqual(args[args.index("-c:v") + 1], "libx264")
            self.assertEqual(args[args.index("-frames:v") + 1], "150")
            self.assertIn("1920:1080", args[args.index("-filter_complex") + 1])

    def test_manual_upload_assignment_uses_semantic_media_role(self) -> None:
        media_file = MediaFile(
            id="manual-media",
            path=str(self.root / "manual.mp4"),
            filename="manual.mp4",
            media_type="video",
            file_hash="manual-hash",
            library_role="semantic",
        )
        shot = MediaShot(
            id="manual-shot",
            media_file_id=media_file.id,
            shot_index=1,
            library_role="semantic",
        )
        assignment = SceneAssignment(
            id="manual-assignment",
            project_id="project-1",
            scene_id="scene-1",
            media_shot_id=shot.id,
            selection_stage="manual_upload",
        )

        scene_renderer.validate_semantic_assignment(assignment, shot, media_file)

    def test_two_short_shots_cover_and_render_one_scene(self) -> None:
        with Session(self.engine) as session:
            project, scene = self._project_with_scene(session)
            scene.end_ms = 10_000
            session.add(scene)
            clips = []
            for index in (1, 2):
                source = self.root / f"source-{index}.mp4"
                source.write_bytes(b"video")
                media = MediaFile(
                    id=f"media-{index}",
                    path=str(source),
                    filename=source.name,
                    media_type="video",
                    file_hash=f"hash-{index}",
                    duration_ms=5_000,
                    width=1920,
                    height=1080,
                )
                shot = MediaShot(
                    id=f"shot-{index}",
                    media_file_id=media.id,
                    shot_index=1,
                    start_ms=0,
                    end_ms=5_000,
                )
                assignment = SceneAssignment(
                    id=f"assignment-{index}",
                    project_id=project.id,
                    scene_id=scene.id,
                    media_shot_id=shot.id,
                    sequence_index=index,
                )
                session.add_all([media, shot, assignment])
                clips.append(assignment)
            session.commit()
            settings = SimpleNamespace(workspace_dir=self.root)

            def fake_ffmpeg(args, _project_id):
                Path(args[-1]).write_bytes(b"mp4")

            with (
                patch.object(scene_renderer, "get_settings", return_value=settings),
                patch.object(scene_renderer, "run_ffmpeg", side_effect=fake_ffmpeg) as ffmpeg,
                patch.object(
                    scene_renderer,
                    "check_scene_video",
                    return_value=self._quality(10.0),
                ),
            ):
                scene_renderer.render_scene(session, project, scene, clips)

            coverage = timeline_composer.scene_coverage(session, scene)
            args = ffmpeg.call_args.args[0]
            self.assertTrue(coverage["complete"])
            self.assertEqual(args.count("-i"), 2)
            self.assertIn("concat=n=2:v=1:a=0", args[args.index("-filter_complex") + 1])

    def test_small_duration_gap_uses_only_mild_slowdown(self) -> None:
        with Session(self.engine) as session:
            project, scene = self._project_with_scene(session)
            scene.end_ms = 11_000
            session.add(scene)
            media, shot = self._media(session)
            media.duration_ms = 10_000
            shot.end_ms = 10_000
            assignment = SceneAssignment(
                id="slow-assignment",
                project_id=project.id,
                scene_id=scene.id,
                media_shot_id=shot.id,
            )
            session.add_all([media, shot, assignment])
            session.commit()

            coverage = timeline_composer.scene_coverage(session, scene)

            self.assertTrue(coverage["complete"])
            self.assertGreaterEqual(assignment.playback_speed, 0.85)
            self.assertAlmostEqual(assignment.playback_speed, 10 / 11, places=3)

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
            project_dir = self.root / "Project"
            audio = self.root / "Project.wav"
            video = self.root / "Project.mp4"
            subtitle = self.root / "Project.srt"
            project_dir.mkdir(parents=True)
            for path in (audio, video, subtitle):
                path.write_bytes(b"data")
            scene_path = project_dir / "renders" / "scenes" / "scene_0001.mp4"
            scene_path.parent.mkdir(parents=True, exist_ok=True)
            scene_path.write_bytes(b"scene")
            visual_track = project_dir / "renders" / "visual_track.mp4"
            visual_track.write_bytes(b"visual")

            with (
                patch.object(qa_service, "get_settings", return_value=settings),
                patch.object(scene_renderer, "get_settings", return_value=settings),
                patch.object(qa_service, "probe_duration", return_value=5.0),
                patch.object(
                    qa_service,
                    "probe_media",
                    return_value={
                        "width": 1920,
                        "height": 1080,
                        "codec_name": "h264",
                        "audio_stream_count": 0,
                    },
                ),
            ):
                report = qa_service.run_quality_check(session, project)

            self.assertTrue(report["passed"])
            self.assertEqual(report["issues"], [])
            self.assertTrue((project_dir / "reports" / "qa.json").is_file())

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

    @staticmethod
    def _quality(duration: float) -> dict:
        return {
            "passed": True,
            "metadata": {
                "duration_ms": round(duration * 1000),
                "width": 1920,
                "height": 1080,
                "codec_name": "h264",
                "pixel_format": "yuv420p",
                "frame_rate_value": 30.0,
                "video_stream_count": 1,
                "audio_stream_count": 0,
            },
            "issues": [],
        }

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
