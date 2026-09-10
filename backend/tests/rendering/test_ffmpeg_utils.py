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
            '"height":1080,"sample_aspect_ratio":"1:1",'
            '"display_aspect_ratio":"16:9","pix_fmt":"yuv420p",'
            '"avg_frame_rate":"30000/1001",'
            '"time_base":"1/30000","duration_ts":"60060","nb_frames":"60"},'
            '{"codec_type":"audio","codec_name":"aac"}]}',
            "",
        )

        result = ffmpeg.probe_media(Path("sample.mp4"))

        self.assertEqual(result["video_stream_count"], 1)
        self.assertEqual(result["audio_stream_count"], 1)
        self.assertEqual(result["pixel_format"], "yuv420p")
        self.assertEqual(result["sample_aspect_ratio"], "1:1")
        self.assertEqual(result["display_aspect_ratio"], "16:9")
        self.assertEqual(result["time_base"], "1/30000")
        self.assertEqual(result["duration_ts"], 60060)
        self.assertEqual(result["frame_count"], 60)
        self.assertAlmostEqual(result["frame_rate_value"], 29.97003, places=4)

    @patch("app.infrastructure.ffmpeg._resolve_tool", return_value="ffmpeg")
    @patch("app.infrastructure.ffmpeg.subprocess.run")
    def test_detect_silence_intervals_parses_complete_pairs(self, run_mock, _resolve_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            [],
            0,
            "",
            "[silencedetect] silence_start: 10.25\n"
            "[silencedetect] silence_end: 10.85 | silence_duration: 0.60\n"
            "[silencedetect] silence_start: 42.0\n"
            "[silencedetect] silence_end: 42.5 | silence_duration: 0.50\n",
        )

        intervals = ffmpeg.detect_silence_intervals(Path("voice.wav"))

        self.assertEqual(intervals, [(10.25, 10.85), (42.0, 42.5)])

    @patch("app.infrastructure.ffmpeg._run_ffmpeg_analysis")
    def test_audio_quality_parser_reports_volume_and_long_silence(self, run_mock) -> None:
        run_mock.return_value = (
            "mean_volume: -31.5 dB\nmax_volume: -0.0 dB\n"
            "silence_start: 10.0\nsilence_end: 16.5 | silence_duration: 6.5\n"
        )

        result = ffmpeg.analyze_audio_quality(Path("voice.wav"), "project-1")

        self.assertEqual(result["mean_volume_db"], -31.5)
        self.assertEqual(result["max_volume_db"], 0.0)
        self.assertEqual(result["silence_intervals"][0]["duration"], 6.5)

    @patch("app.infrastructure.ffmpeg._run_ffmpeg_analysis")
    def test_video_anomaly_parser_reports_black_and_freeze_ranges(self, run_mock) -> None:
        run_mock.return_value = (
            "black_start:1.0 black_end:3.5 black_duration:2.5\n"
            "freeze_start: 8.0\nfreeze_end: 12.0 | freeze_duration: 4.0\n"
        )

        result = ffmpeg.detect_video_anomalies(Path("video.mp4"), "project-1")

        self.assertEqual(result["black_intervals"][0]["duration"], 2.5)
        self.assertEqual(result["freeze_intervals"][0]["duration"], 4.0)


if __name__ == "__main__":
    unittest.main()
