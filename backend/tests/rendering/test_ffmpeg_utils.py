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

    @patch("app.infrastructure.ffmpeg._resolve_tool", return_value="ffprobe")
    @patch("app.infrastructure.ffmpeg.subprocess.run")
    def test_probe_media_reports_stream_counts_and_frame_rate(
        self, run_mock, _resolve_mock
    ) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            [],
            0,
            '{"format":{"duration":"2.0","format_name":"mov,mp4"},'
            '"streams":[{"codec_type":"video","codec_name":"h264","width":1920,'
            '"height":1080,"pix_fmt":"yuv420p","avg_frame_rate":"30000/1001"},'
            '{"codec_type":"audio","codec_name":"aac"}]}',
            "",
        )

        result = ffmpeg.probe_media(Path("sample.mp4"))

        self.assertEqual(result["video_stream_count"], 1)
        self.assertEqual(result["audio_stream_count"], 1)
        self.assertEqual(result["pixel_format"], "yuv420p")
        self.assertAlmostEqual(result["frame_rate_value"], 29.97003, places=4)


if __name__ == "__main__":
    unittest.main()
