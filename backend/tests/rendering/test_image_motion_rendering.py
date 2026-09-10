import json
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
    timeline_composer,
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
        alternative = motion_presets.select_motion_preset("project-1", scene, assignment, [first])

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
                    scene_quality_checker.check_scene_video(path, 5.0, ProjectRenderConfig())

    def test_scene_quality_uses_frame_count_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "scene.mp4"
            path.write_bytes(b"video")
            metadata = {
                "duration_ms": 5067,
                "width": 1920,
                "height": 1080,
                "codec_name": "h264",
                "pixel_format": "yuv420p",
                "frame_rate_value": 30.0,
                "frame_count": 152,
                "video_stream_count": 1,
                "audio_stream_count": 0,
            }
            with patch.object(scene_quality_checker, "probe_media", return_value=metadata):
                with self.assertRaisesRegex(RuntimeError, "帧数误差 2 帧"):
                    scene_quality_checker.check_scene_video(
                        path,
                        5.0,
                        ProjectRenderConfig(),
                        expected_frame_count=150,
                    )

    def test_absolute_frame_windows_do_not_accumulate_rounding_error(self) -> None:
        boundaries = [
            0,
            6000,
            16720,
            26640,
            34560,
            44560,
            49920,
            59680,
            69680,
            80720,
            93840,
            102800,
            110240,
            120240,
            134480,
        ]
        scenes = [
            VisualScene(
                id=f"scene-{index}",
                project_id="project-1",
                scene_index=index,
                start_ms=start,
                end_ms=end,
                narration="test",
            )
            for index, (start, end) in enumerate(zip(boundaries, boundaries[1:]), start=1)
        ]

        windows = [timeline_composer.scene_frame_window(scene, 30) for scene in scenes]

        self.assertTrue(
            all(current[1] == following[0] for current, following in zip(windows, windows[1:]))
        )
        self.assertEqual(sum(window[2] for window in windows), 4034)
        self.assertEqual(sum(window[2] for window in windows), windows[-1][1] - windows[0][0])

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
        self.assertIn("format=yuv420p,setsar=1,setparams=range=tv", value)
        self.assertIn("trim=end_frame=60", value)

    def test_video_filter_forces_square_sample_aspect_ratio(self) -> None:
        media = SimpleNamespace(media_type="video", width=1920, height=1080)
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
            "source_video",
            ProjectRenderConfig().video,
        )

        self.assertIn("format=yuv420p,setsar=1,setparams=range=tv", value)

    def test_scene_quality_rejects_non_square_sample_aspect_ratio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "scene.mp4"
            path.write_bytes(b"video")
            metadata = {
                "duration_ms": 5000,
                "width": 1920,
                "height": 1080,
                "sample_aspect_ratio": "4201:3840",
                "codec_name": "h264",
                "pixel_format": "yuv420p",
                "frame_rate_value": 30.0,
                "frame_count": 150,
                "video_stream_count": 1,
                "audio_stream_count": 0,
            }
            with patch.object(scene_quality_checker, "probe_media", return_value=metadata):
                with self.assertRaisesRegex(RuntimeError, "像素宽高比不是 1:1"):
                    scene_quality_checker.check_scene_video(
                        path,
                        5.0,
                        ProjectRenderConfig(),
                        expected_frame_count=150,
                    )

    def test_scene_filter_uses_absolute_frame_window_for_round_up_boundaries(self) -> None:
        video_config = ProjectRenderConfig().video
        media = SimpleNamespace(media_type="image", width=1920, height=1080)
        shot = SimpleNamespace(start_ms=0)

        for scene_start_ms, scene_end_ms, expected_frames in [
            (46080, 57520, 344),
            (135040, 139520, 135),
        ]:
            assignment = SceneAssignment(
                id=f"assignment-{scene_start_ms}",
                project_id="project-1",
                scene_id=f"scene-{scene_start_ms}",
                media_shot_id="shot-1",
                scene_offset_start_ms=0,
                scene_offset_end_ms=scene_end_ms - scene_start_ms,
            )
            args = scene_renderer._scene_ffmpeg_args(
                Path("scene.mp4"),
                expected_frames,
                scene_start_ms,
                [(assignment, shot, media, Path("image.png"))],
                ["slow_zoom_in"],
                video_config,
            )

            filter_graph = args[args.index("-filter_complex") + 1]
            self.assertIn(f"trim=end_frame={expected_frames}", filter_graph)
            self.assertEqual(args[args.index("-frames:v") + 1], str(expected_frames))

    def test_scene_filter_allocates_multiple_clips_without_frame_drift(self) -> None:
        video_config = ProjectRenderConfig().video
        media = SimpleNamespace(media_type="image", width=1920, height=1080)
        shot = SimpleNamespace(start_ms=0)
        assignments = [
            SceneAssignment(
                id="assignment-1",
                project_id="project-1",
                scene_id="scene-1",
                media_shot_id="shot-1",
                sequence_index=1,
                scene_offset_start_ms=0,
                scene_offset_end_ms=5000,
            ),
            SceneAssignment(
                id="assignment-2",
                project_id="project-1",
                scene_id="scene-1",
                media_shot_id="shot-2",
                sequence_index=2,
                scene_offset_start_ms=5000,
                scene_offset_end_ms=11440,
            ),
        ]

        args = scene_renderer._scene_ffmpeg_args(
            Path("scene.mp4"),
            344,
            46080,
            [
                (assignments[0], shot, media, Path("image-1.png")),
                (assignments[1], shot, media, Path("image-2.png")),
            ],
            ["slow_zoom_in", "slow_zoom_out"],
            video_config,
        )

        filter_graph = args[args.index("-filter_complex") + 1]
        self.assertIn("trim=end_frame=150", filter_graph)
        self.assertIn("trim=end_frame=194", filter_graph)
        self.assertEqual(args[args.index("-frames:v") + 1], "344")

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
                manifest_path = scene_path.parent / "manifest.json"
                manifest_path.write_text(
                    json.dumps({scene.id: {"duration_seconds": 5.0}}),
                    encoding="utf-8",
                )
                settings = SimpleNamespace(workspace_dir=root)

                def fake_ffmpeg(args, _project_id):
                    Path(args[-1]).write_bytes(b"track")

                with (
                    patch.object(visual_track_composer, "get_settings", return_value=settings),
                    patch.object(
                        visual_track_composer, "run_ffmpeg", side_effect=fake_ffmpeg
                    ) as run,
                    patch.object(scene_renderer, "render_all_scenes") as rerender,
                    patch.object(
                        visual_track_composer,
                        "check_scene_video",
                        return_value={"passed": True},
                    ) as check,
                ):
                    result = visual_track_composer.compose_visual_track(session, project)

                args = run.call_args.args[0]
                self.assertEqual(args[args.index("-c:v") + 1], "copy")
                self.assertIn("-an", args)
                self.assertEqual(check.call_args.kwargs["expected_frame_count"], 150)
                rerender.assert_called_once_with(session, project)
                self.assertTrue(Path(result["path"]).is_file())
            engine.dispose()

    def test_visual_track_transition_keeps_total_scene_frame_count(self) -> None:
        video_config = ProjectRenderConfig().video
        args = visual_track_composer.build_scene_transition_args(
            [Path("scene_0001.mp4"), Path("scene_0002.mp4"), Path("scene_0003.mp4")],
            [4.0, 5.0, 6.0],
            [
                visual_track_composer.PlannedTransition(1, "fade", 0.45),
                visual_track_composer.PlannedTransition(2, "dissolve", 0.45),
            ],
            Path("visual_track.mp4"),
            video_config,
            450,
        )

        graph = args[args.index("-filter_complex") + 1]
        self.assertIn(
            "[0:v]settb=AVTB,setpts=PTS-STARTPTS,setsar=1,tpad=stop_mode=clone:stop_duration=0.450",
            graph,
        )
        self.assertIn("[1:v]settb=AVTB,setpts=PTS-STARTPTS,setsar=1", graph)
        self.assertIn("[2:v]settb=AVTB,setpts=PTS-STARTPTS,setsar=1", graph)
        self.assertIn("xfade=transition=fade:duration=0.450:offset=4.000", graph)
        self.assertIn("xfade=transition=dissolve:duration=0.450:offset=9.000", graph)
        self.assertEqual(args[args.index("-frames:v") + 1], "450")

    def test_visual_track_writes_large_transition_graph_to_script(self) -> None:
        video_config = ProjectRenderConfig().video
        args = visual_track_composer.build_scene_transition_args(
            [Path("scene_0001.mp4"), Path("scene_0002.mp4")],
            [4.0, 5.0],
            [visual_track_composer.PlannedTransition(1, "fade", 0.45)],
            Path("visual_track.mp4"),
            video_config,
            270,
        )

        with tempfile.TemporaryDirectory() as temporary:
            script_path = Path(temporary) / "visual_track_filter.txt"
            command = visual_track_composer._externalize_filter_graph(args, script_path)

            self.assertNotIn("-filter_complex", command)
            self.assertEqual(
                command[command.index("-filter_complex_script") + 1],
                str(script_path),
            )
            graph = script_path.read_text(encoding="utf-8")
            self.assertIn(
                "[0:v]settb=AVTB,setpts=PTS-STARTPTS,setsar=1",
                graph,
            )
            self.assertIn("xfade=transition=fade", graph)

    def test_visual_track_rejects_two_effects_on_same_boundary(self) -> None:
        with self.assertRaisesRegex(ValueError, "Only one transition effect"):
            visual_track_composer.build_scene_transition_args(
                [Path("one.mp4"), Path("two.mp4")],
                [3.0, 3.0],
                [
                    visual_track_composer.PlannedTransition(1, "fade", 0.45),
                    visual_track_composer.PlannedTransition(1, "dissolve", 0.45),
                ],
                Path("out.mp4"),
                ProjectRenderConfig().video,
                180,
            )

    def test_old_timing_manifest_forces_scene_rerender_on_visual_track_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = Project(id="project-1", name="Project", output_dir=str(root))
            scene = VisualScene(
                id="scene-1",
                project_id=project.id,
                scene_index=1,
                start_ms=46080,
                end_ms=57520,
                narration="test",
            )
            manifest_path = root / "Project" / "renders" / "scenes" / "manifest.json"
            manifest_path.parent.mkdir(parents=True)
            manifest_path.write_text(
                json.dumps(
                    {
                        scene.id: {
                            "start_frame": 1382,
                            "end_frame": 1726,
                            "frame_count": 344,
                        }
                    }
                ),
                encoding="utf-8",
            )
            settings = SimpleNamespace(workspace_dir=root)

            with patch.object(scene_renderer, "get_settings", return_value=settings):
                self.assertTrue(
                    scene_renderer.scene_renders_need_timing_refresh(
                        project, [scene], ProjectRenderConfig()
                    )
                )

                manifest_path.write_text(
                    json.dumps(
                        {
                            scene.id: {
                                "render_timing_version": scene_renderer.RENDER_TIMING_VERSION,
                                "start_frame": 1382,
                                "end_frame": 1726,
                                "frame_count": 344,
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                self.assertFalse(
                    scene_renderer.scene_renders_need_timing_refresh(
                        project, [scene], ProjectRenderConfig()
                    )
                )


if __name__ == "__main__":
    unittest.main()
