import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import video_service


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

            with patch.object(Path, "replace", flaky_replace), patch("app.services.video_service.time.sleep"):
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

    @patch("app.services.video_service.run_ffmpeg")
    def test_normalizing_skips_source_first_frames(self, run_mock) -> None:
        selected = [
            video_service.SelectedVideo(Path("source.mp4"), "source", 2.0, 1.9)
        ]

        with tempfile.TemporaryDirectory() as directory:
            video_service.normalize_selected_clips(selected, Path(directory))

        args = run_mock.call_args.args[0]
        self.assertEqual(args[args.index("-ss") + 1], "0.100")
        self.assertEqual(args[args.index("-t") + 1], "1.900")

    @patch("app.services.video_service.run_ffmpeg")
    def test_final_concat_reencodes_without_audio(self, run_mock) -> None:
        video_service.concatenate_normalized_clips(
            Path("concat.txt"), Path("out.mp4")
        )

        args = run_mock.call_args.args[0]
        self.assertNotIn("copy", args)
        self.assertEqual(args[args.index("-c:v") + 1], "libx264")
        self.assertEqual(args[args.index("-pix_fmt") + 1], "yuv420p")
        self.assertIn("tpad=stop_mode=clone:stop_duration=0.500", args)
        self.assertEqual(args.count("-i"), 1)
        self.assertIn("-an", args)
        self.assertNotIn("voice.wav", args)

    @patch("app.services.video_service.run_ffmpeg")
    def test_final_concat_accepts_measured_tail_padding(self, run_mock) -> None:
        video_service.concatenate_normalized_clips(
            Path("concat.txt"), Path("out.mp4"), 0.981
        )

        args = run_mock.call_args.args[0]
        self.assertIn("tpad=stop_mode=clone:stop_duration=0.981", args)

    @patch("app.services.video_service.random.choice", side_effect=lambda paths: paths[0])
    @patch("app.services.video_service.random.shuffle")
    @patch("app.services.video_service.probe_duration")
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


if __name__ == "__main__":
    unittest.main()
