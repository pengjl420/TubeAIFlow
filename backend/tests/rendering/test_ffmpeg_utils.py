import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from app.infrastructure import ffmpeg


class FfmpegUtilsTests(unittest.TestCase):
    @patch("app.infrastructure.ffmpeg._resolve_tool", return_value="ffmpeg")
    @patch("app.infrastructure.ffmpeg.subprocess.run")
    def test_run_ffmpeg_uses_stable_output_decoding(self, run_mock, _resolve_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess([], 0, "", "")

        ffmpeg.run_ffmpeg(["-version"])

        kwargs = run_mock.call_args.kwargs
        self.assertEqual(kwargs["encoding"], "utf-8")
        self.assertEqual(kwargs["errors"], "replace")

    @patch("app.infrastructure.ffmpeg._resolve_tool", return_value="ffprobe")
    @patch("app.infrastructure.ffmpeg.subprocess.run")
    def test_probe_duration_uses_stable_output_decoding(self, run_mock, _resolve_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            [], 0, '{"format": {"duration": "1.25"}}', ""
        )

        duration = ffmpeg.probe_duration(Path("sample.mp4"))

        self.assertEqual(duration, 1.25)
        kwargs = run_mock.call_args.kwargs
        self.assertEqual(kwargs["encoding"], "utf-8")
        self.assertEqual(kwargs["errors"], "replace")


if __name__ == "__main__":
    unittest.main()
