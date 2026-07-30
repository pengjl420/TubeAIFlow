import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import StoryboardTransitionEffect
from app.services.rendering import rough_cut_service as video_service


class VideoServiceTests(unittest.TestCase):
    def test_write_video_progress_retries_permission_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "progress.json"
            original_replace = Path.replace
            attempts = 0

            def flaky_replace(source: Path, target: Path) -> Path:
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise PermissionError("busy")
                return original_replace(source, target)

            with patch.object(Path, "replace", flaky_replace), patch("app.services.rendering.rough_cut_service.time.sleep"):
                video_service.write_video_progress(path, "running", "normalizing", 25)

            self.assertEqual(attempts, 2)
            self.assertEqual(video_service.json.loads(path.read_text(encoding="utf-8"))["percent"], 25)
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_compose_video_rejects_duplicate_project(self) -> None:
        project = type("ProjectStub", (), {"id": "project-1"})()
        video_service._composing_project_ids.add(project.id)
        try:
            with self.assertRaisesRegex(video_service.VideoCompositionRunningError, "already running"):
                video_service.compose_video(object(), project)
        finally:
            video_service._composing_project_ids.discard(project.id)

    @patch(
        "app.services.rendering.rough_cut_service.probe_media",
        return_value={
            "width": 1920,
            "height": 1080,
            "sample_aspect_ratio": "1:1",
            "frame_rate_value": 30.0,
            "pixel_format": "yuv420p",
            "audio_stream_count": 0,
        },
    )
    @patch("app.services.rendering.rough_cut_service.run_ffmpeg")
    def test_normalizing_skips_source_first_frames(self, run_mock, _probe_mock) -> None:
        selected = [
            video_service.SelectedVideo(Path("source.mp4"), "source", 2.0, 1.9)
        ]

        with tempfile.TemporaryDirectory() as directory:
            video_service.normalize_selected_clips(selected, Path(directory))

        args = run_mock.call_args.args[0]
        self.assertEqual(args[args.index("-ss") + 1], "0.100")
        self.assertEqual(args[args.index("-t") + 1], "1.900")
        self.assertIn("setsar=1", args[args.index("-vf") + 1])
        self.assertIn("out_range=tv", args[args.index("-vf") + 1])
        self.assertIn("setparams=range=tv", args[args.index("-vf") + 1])

    @patch(
        "app.services.rendering.rough_cut_service.probe_media",
        return_value={
            "width": 1920,
            "height": 1080,
            "sample_aspect_ratio": "6301:5760",
            "frame_rate_value": 30.0,
            "pixel_format": "yuv420p",
            "audio_stream_count": 0,
        },
    )
    def test_normalized_clip_rejects_non_square_sample_aspect_ratio(self, _probe_mock) -> None:
        with self.assertRaisesRegex(RuntimeError, "SAR=6301:5760"):
            video_service._validate_normalized_clip(
                Path("0009.mp4"),
                Path("source-with-non-square-pixels.mp4"),
            )

    @patch("app.services.rendering.rough_cut_service.run_ffmpeg")
    def test_final_concat_reencodes_without_audio(self, run_mock) -> None:
        video_service.concatenate_normalized_clips(
            Path("concat.txt"), Path("out.mp4")
        )

        args = run_mock.call_args.args[0]
        self.assertNotIn("copy", args)
        self.assertEqual(args[args.index("-c:v") + 1], "libx264")
        self.assertEqual(args[args.index("-pix_fmt") + 1], "yuv420p")
        final_filter = args[args.index("-vf") + 1]
        self.assertIn("tpad=stop_mode=clone:stop_duration=0.500", final_filter)
        self.assertIn("setsar=1", final_filter)
        self.assertEqual(args.count("-i"), 1)
        self.assertIn("-an", args)
        self.assertNotIn("voice.wav", args)

    @patch("app.services.rendering.rough_cut_service.run_ffmpeg")
    def test_final_concat_accepts_measured_tail_padding(self, run_mock) -> None:
        video_service.concatenate_normalized_clips(
            Path("concat.txt"), Path("out.mp4"), 0.981
        )

        args = run_mock.call_args.args[0]
        self.assertIn(
            "tpad=stop_mode=clone:stop_duration=0.981",
            args[args.index("-vf") + 1],
        )

    def test_transition_filter_mixes_xfade_with_hard_cuts(self) -> None:
        filter_graph = video_service.build_transition_filter(
            [4.0, 4.0, 4.0],
            [video_service.PlannedTransition(1, "fade", 0.45)],
        )

        self.assertIn("xfade=transition=fade:duration=0.450:offset=3.550", filter_graph)
        self.assertIn("[join1][v2]concat=n=2:v=1:a=0[join2]", filter_graph)
        self.assertIn("tpad=stop_mode=clone:stop_duration=0.500", filter_graph)
        self.assertIn("[0:v]settb=AVTB,setpts=PTS-STARTPTS,setsar=1[v0]", filter_graph)
        self.assertIn(
            "fps=30,setsar=1,format=yuv420p,setparams=range=tv[vout]",
            filter_graph,
        )

    @patch("app.services.rendering.rough_cut_service.run_ffmpeg")
    def test_transition_concat_uses_all_video_inputs_and_filter_script(self, run_mock) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script_path = root / "transition_filter.txt"
            video_service.concatenate_clips_with_transitions(
                [root / "one.mp4", root / "two.mp4"],
                [3.0, 3.0],
                script_path,
                [video_service.PlannedTransition(1, "dissolve", 0.45)],
                root / "out.mp4",
            )

            self.assertTrue(script_path.is_file())
            args = run_mock.call_args.args[0]
            self.assertEqual(args.count("-i"), 2)
            self.assertIn("-filter_complex_script", args)
            self.assertIn("xfade=transition=dissolve", script_path.read_text(encoding="utf-8"))

    @patch("app.services.rendering.rough_cut_service.random.choices", return_value=["fade"])
    @patch("app.services.rendering.rough_cut_service.random.sample", side_effect=lambda values, count: values[:count])
    @patch("app.services.rendering.rough_cut_service.random.randint", side_effect=[3, 1, 3, 1])
    def test_transition_plan_adds_only_some_boundaries(
        self, _randint_mock, _sample_mock, _choices_mock
    ) -> None:
        selected = [
            video_service.SelectedVideo(Path(f"{index}.mp4"), str(index), 3.0, 2.9)
            for index in range(6)
        ]
        effects = [StoryboardTransitionEffect(name="fade", percentage=100)]

        plan = video_service.build_transition_plan(selected, effects)

        self.assertEqual([item.after_clip_index for item in plan], [1, 4])
        self.assertTrue(all(item.effect == "fade" for item in plan))
        self.assertLess(len(plan), len(selected) - 1)

    @patch("app.services.rendering.rough_cut_service.random.choice", side_effect=lambda paths: paths[0])
    @patch("app.services.rendering.rough_cut_service.random.shuffle")
    @patch("app.services.rendering.rough_cut_service.probe_duration")
    def test_selection_keeps_last_clip_in_full(
        self, probe_mock, _shuffle_mock, _choice_mock
    ) -> None:
        probe_mock.side_effect = [4.1, 4.1]
        groups = {
            "one": [Path("one.mp4")],
            "two": [Path("two.mp4")],
        }

        selected = video_service.select_videos_for_duration(groups, 5.0)

        self.assertEqual(len(selected), 2)
        for item in selected:
            self.assertAlmostEqual(item.clip_duration, 4.0)
        self.assertGreater(sum(item.clip_duration for item in selected), 5.0)

    @patch("app.services.rendering.rough_cut_service.random.choice", side_effect=lambda paths: paths[0])
    @patch("app.services.rendering.rough_cut_service.random.shuffle")
    @patch("app.services.rendering.rough_cut_service.probe_duration", side_effect=[2.1, 2.1])
    def test_selection_reserves_duration_for_transition_overlap(
        self, _probe_mock, _shuffle_mock, _choice_mock
    ) -> None:
        groups = {"one": [Path("one.mp4")], "two": [Path("two.mp4")]}

        with self.assertRaisesRegex(ValueError, "before transitions"):
            video_service.select_videos_for_duration(groups, 3.8, 0.45)

    def test_rough_cut_scans_configured_directory_without_using_media_library(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "nested"
            nested.mkdir()
            first_path = root / "landscape.mp4"
            second_path = nested / "other.mov"
            ignored_path = root / "notes.txt"
            first_path.write_bytes(b"landscape")
            second_path.write_bytes(b"other")
            ignored_path.write_text("not video", encoding="utf-8")

            selected = video_service.list_rough_cut_video_files(root)

        self.assertEqual(selected, [first_path, second_path])


if __name__ == "__main__":
    unittest.main()
