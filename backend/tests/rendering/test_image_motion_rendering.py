import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

from app.models.media import SceneAssignment
from app.models.project import Project
from app.models.storyboard import VisualScene
from app.schemas.render import ProjectRenderConfig
from app.services.rendering import (
    motion_presets,
    scene_quality_checker,
    scene_renderer,
    visual_track_composer,
)


class ImageMotionRenderingTests(unittest.TestCase):
    def test_auto_preset_is_stable_and_avoids_immediate_repeat(self) -> None:
        scene = VisualScene(
            id="scene-1",
            project_id="project-1",
            scene_index=1,
            start_ms=0,
            end_ms=5000,
            narration="城市环境",
            storyboard_json='{"visual_type":"city"}',
        )
        assignment = SceneAssignment(
            id="assignment-1",
            project_id="project-1",
            scene_id=scene.id,
            media_shot_id="shot-1",
            motion_type="auto",
        )
        first = motion_presets.select_motion_preset("project-1", scene, assignment)
        second = motion_presets.select_motion_preset("project-1", scene, assignment)
        alternative = motion_presets.select_motion_preset(
            "project-1", scene, assignment, [first]
        )

        self.assertEqual(first, second)
        self.assertNotEqual(first, alternative)

    def test_scene_quality_rejects_audio_stream(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "scene.mp4"
            path.write_bytes(b"video")
            metadata = {
                "duration_ms": 5000,
                "width": 1920,
                "height": 1080,
                "codec_name": "h264",
                "pixel_format": "yuv420p",
                "frame_rate_value": 30.0,
                "video_stream_count": 1,
                "audio_stream_count": 1,
            }
            with patch.object(scene_quality_checker, "probe_media", return_value=metadata):
                with self.assertRaisesRegex(RuntimeError, "意外音频流"):
                    scene_quality_checker.check_scene_video(
                        path, 5.0, ProjectRenderConfig()
                    )

    def test_image_filter_forces_limited_range_yuv420p(self) -> None:
        media = SimpleNamespace(media_type="image", width=1920, height=1080)
        assignment = SceneAssignment(
            id="assignment-1",
            project_id="project-1",
            scene_id="scene-1",
            media_shot_id="shot-1",
        )

        value = scene_renderer._visual_filter(
            0,
            media,
            2.0,
            1.0,
            "out",
            assignment,
            "slow_zoom_in",
            ProjectRenderConfig().video,
        )

        self.assertIn("out_range=tv", value)
        self.assertIn("format=yuv420p,setparams=range=tv", value)

    def test_visual_track_uses_stream_copy_and_no_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            engine = create_engine(
                f"sqlite:///{root / 'test.db'}",
                connect_args={"check_same_thread": False},
            )
            SQLModel.metadata.create_all(engine)
            with Session(engine) as session:
                project = Project(id="project-1", name="Project", output_dir=str(root))
                scene = VisualScene(
                    id="scene-1",
                    project_id=project.id,
                    scene_index=1,
                    start_ms=0,
                    end_ms=5000,
                    narration="测试",
                )
                session.add_all([project, scene])
                session.commit()
                work_dir = root / "Project"
                scene_path = work_dir / "renders" / "scenes" / "scene_0001.mp4"
                scene_path.parent.mkdir(parents=True)
                scene_path.write_bytes(b"scene")
                settings = SimpleNamespace(workspace_dir=root)

                def fake_ffmpeg(args, _project_id):
                    Path(args[-1]).write_bytes(b"track")

                with (
                    patch.object(visual_track_composer, "get_settings", return_value=settings),
                    patch.object(visual_track_composer, "run_ffmpeg", side_effect=fake_ffmpeg) as run,
                    patch.object(
                        visual_track_composer,
                        "check_scene_video",
                        return_value={"passed": True},
                    ),
                ):
                    result = visual_track_composer.compose_visual_track(session, project)

                args = run.call_args.args[0]
                self.assertEqual(args[args.index("-c:v") + 1], "copy")
                self.assertIn("-an", args)
                self.assertTrue(Path(result["path"]).is_file())
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
