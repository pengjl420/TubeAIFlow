import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models.project import Project
from app.models.storyboard import SubtitleCue, VisualScene
from app.services.rendering import final_renderer, preview_renderer


class PreviewAndFinalRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.settings = SimpleNamespace(workspace_dir=self.root)
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temp_dir.cleanup()

    def _seed(self, session: Session) -> Project:
        project = Project(id="p1", name="Project", output_dir=str(self.root))
        session.add(project)
        session.add(
            VisualScene(
                id="scene-1",
                project_id=project.id,
                scene_index=1,
                start_ms=0,
                end_ms=120_000,
                narration="Narration",
            )
        )
        session.add(
            SubtitleCue(
                id="cue-1",
                project_id=project.id,
                source_segment_id="segment-1",
                cue_index=1,
                start_ms=35_000,
                end_ms=37_000,
                text="Preview caption",
            )
        )
        session.commit()
        work_dir = self.root / "Project"
        (work_dir / "renders").mkdir(parents=True)
        (work_dir / "renders" / "visual_track.mp4").write_bytes(b"video")
        (self.root / "Project.wav").write_bytes(b"audio")
        (self.root / "Project.srt").write_text(
            "1\n00:00:35,000 --> 00:00:37,000\nCaption\n", encoding="utf-8"
        )
        return project

    def test_range_preview_shifts_subtitles_and_reuses_cached_output(self) -> None:
        commands = []

        def fake_run(args, _project_id):
            commands.append(args)
            Path(args[-1]).write_bytes(b"preview")

        with Session(self.engine) as session:
            project = self._seed(session)
            with (
                patch.object(preview_renderer, "get_settings", return_value=self.settings),
                patch.object(preview_renderer, "probe_duration", return_value=120.0),
                patch.object(preview_renderer, "run_ffmpeg", side_effect=fake_run),
            ):
                first = preview_renderer.render_timeline_preview(
                    session, project, start_ms=30_000, duration_ms=30_000
                )
                second = preview_renderer.render_timeline_preview(
                    session, project, start_ms=30_000, duration_ms=30_000
                )
                cue = session.get(SubtitleCue, "cue-1")
                cue.text = "Changed caption"
                session.add(cue)
                session.commit()
                changed = preview_renderer.render_timeline_preview(
                    session, project, start_ms=30_000, duration_ms=30_000
                )

        self.assertFalse(first["skipped"])
        self.assertTrue(second["skipped"])
        self.assertFalse(changed["skipped"])
        self.assertEqual(len(commands), 2)
        subtitle_path = Path(
            commands[0][commands[0].index("-vf") + 1]
            .split("filename='")[1][:-1]
            .replace(r"\:", ":")
        )
        subtitle_text = subtitle_path.read_text(encoding="utf-8")
        self.assertIn("00:00:05,000 --> 00:00:07,000", subtitle_text)
        self.assertTrue(Path(first["path"]).is_file())

    def test_final_render_burns_subtitles_and_writes_report(self) -> None:
        commands = []

        def fake_run(args, _project_id):
            commands.append(args)
            Path(args[-1]).write_bytes(b"final")

        with Session(self.engine) as session:
            project = self._seed(session)
            with (
                patch.object(final_renderer, "get_settings", return_value=self.settings),
                patch.object(final_renderer, "probe_duration", side_effect=[120.0, 120.0]),
                patch.object(final_renderer, "run_ffmpeg", side_effect=fake_run),
            ):
                result = final_renderer.compose_final_video(session, project)

        self.assertTrue(result["subtitles_burned"])
        self.assertIn("-vf", commands[0])
        self.assertIn("subtitles=filename=", commands[0][commands[0].index("-vf") + 1])
        report_path = self.root / "Project" / "reports" / "render_report.json"
        self.assertEqual(json.loads(report_path.read_text(encoding="utf-8"))["scene_count"], 1)

    def test_range_preview_renders_only_overlapping_scenes_when_track_is_stale(self) -> None:
        commands = []

        def fake_run(args, _project_id):
            commands.append(args)
            Path(args[-1]).write_bytes(b"preview")

        with Session(self.engine) as session:
            project = self._seed(session)
            (self.root / "Project" / "renders" / "visual_track.mp4").unlink()
            scene_path = self.root / "Project" / "renders" / "scenes" / "scene_0001.mp4"
            scene_path.parent.mkdir(parents=True)
            scene_path.write_bytes(b"scene")
            with (
                patch.object(preview_renderer, "get_settings", return_value=self.settings),
                patch.object(preview_renderer, "probe_duration", return_value=120.0),
                patch.object(preview_renderer, "run_ffmpeg", side_effect=fake_run),
                patch.object(
                    preview_renderer.scene_renderer,
                    "render_scene",
                    return_value={"path": str(scene_path)},
                ) as render_scene,
            ):
                result = preview_renderer.render_timeline_preview(
                    session, project, start_ms=30_000, duration_ms=30_000
                )

        render_scene.assert_called_once()
        self.assertFalse(result["skipped"])
        self.assertIn("concat", commands[0])
        self.assertEqual(commands[0][commands[0].index("-ss") + 1], "30.000")


if __name__ == "__main__":
    unittest.main()
