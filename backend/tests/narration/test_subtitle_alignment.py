import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from app.models.narration import Segment
from app.models.project import Project
from app.schemas.subtitle_alignment import AsrWord
from app.services.narration.alignment_service import align_segment, source_units
from app.services.narration.srt_service import create_full_srt, read_alignment_outputs


class FakeBackend:
    name = "fake-whisper"

    def __init__(self, words):
        self.words = words

    def transcribe(self, _audio_path, _language, *, vad_filter=False):
        return self.words


class FailingBackend:
    name = "failed-whisper"

    def transcribe(self, _audio_path, _language, *, vad_filter=False):
        raise RuntimeError("local model failed")


class SubtitleAlignmentTests(unittest.TestCase):
    def test_chinese_alignment_preserves_original_name_and_punctuation(self) -> None:
        text = "张三在2026年，来到北京。"
        backend = FakeBackend(
            [
                AsrWord(text="章三在", start_ms=100, end_ms=900, confidence=0.9),
                AsrWord(text="2026年", start_ms=900, end_ms=1700, confidence=0.95),
                AsrWord(text="来到北京", start_ms=1800, end_ms=3000, confidence=0.96),
            ]
        )

        result = align_segment(
            segment_id="0001",
            display_text=text,
            language="zh",
            duration_ms=3300,
            audio_path=Path("unused.wav"),
            backend=backend,
        )

        self.assertEqual("".join(cue.text for cue in result.cues), text)
        self.assertNotIn("章", "".join(cue.text for cue in result.cues))
        self.assertTrue(all(cue.local_end_ms <= 3300 for cue in result.cues))
        self.assertTrue(all(cue.source_char_end > cue.source_char_start for cue in result.cues))

    def test_missing_source_units_are_interpolated_and_marked(self) -> None:
        text = "人生到了五十岁以后才会明白"
        backend = FakeBackend(
            [
                AsrWord(text="人生到", start_ms=0, end_ms=900),
                AsrWord(text="五十岁以后才会明白", start_ms=1200, end_ms=4000),
            ]
        )

        result = align_segment(
            segment_id="0002",
            display_text=text,
            language="zh",
            duration_ms=4200,
            audio_path=Path("unused.wav"),
            backend=backend,
        )

        missing = next(unit for unit in result.units if unit.text == "了")
        self.assertEqual(missing.source, "interpolated")
        self.assertLess(missing.start_ms, missing.end_ms)
        self.assertEqual("".join(cue.text for cue in result.cues), text)

    def test_backend_failure_falls_back_without_losing_text(self) -> None:
        text = "This is the original AI transcript, not ASR output."
        result = align_segment(
            segment_id="0003",
            display_text=text,
            language="en",
            duration_ms=5000,
            audio_path=Path("unused.wav"),
            backend=FailingBackend(),
        )

        normalized = " ".join("".join(cue.text for cue in result.cues).split())
        self.assertEqual(normalized, " ".join(text.split()))
        self.assertEqual(result.backend, "heuristic")
        self.assertEqual(result.status, "needs_review")
        self.assertIn("local model failed", result.error)

    def test_english_source_units_keep_display_spans(self) -> None:
        text = "Dr. Smith paid $1,250 in 2026."
        units = source_units(text, "en")

        self.assertEqual([item.text for item in units], ["Dr", "Smith", "paid", "1,250", "in", "2026"])
        self.assertEqual(text[units[3].display_start:units[3].display_end], "1,250")

    def test_chinese_numbers_are_normalized_only_for_alignment(self) -> None:
        text = "2026 年增长 3.5%，收入 1,200 元。"
        units = source_units(text, "zh")

        self.assertEqual(
            units[0].normalized,
            "2026",
        )
        self.assertIn("3点5", [item.normalized for item in units])
        result = align_segment(
            segment_id="numbers",
            display_text=text,
            language="zh",
            duration_ms=5000,
            audio_path=Path("unused.wav"),
            backend=FakeBackend(
                [AsrWord(text="二零二六年增长三点五收入一千二百元", start_ms=0, end_ms=4800)]
            ),
        )
        self.assertEqual("".join(cue.text.replace(" ", "") for cue in result.cues), text.replace(" ", ""))
        self.assertGreater(result.text_similarity, 0.8)

    def test_srt_generation_writes_traceable_alignment_and_qa(self) -> None:
        with TemporaryDirectory() as directory:
            settings = SimpleNamespace(
                workspace_dir=Path(directory) / "workspace",
                subtitle_alignment_enabled=True,
                subtitle_whisper_model_path=None,
                subtitle_min_cue_duration_ms=1000,
                subtitle_max_cue_duration_ms=5600,
                subtitle_max_display_units=22,
            )
            project = Project(id="p1", name="原稿字幕", output_dir=directory)
            segment = Segment(
                id="p1:0001",
                project_id="p1",
                segment_id="0001",
                segment_index=1,
                text="最终字幕只能来自这份原始逐字稿。",
                duration=4.0,
                start_time=0.0,
                end_time=4.0,
            )
            with patch("app.services.narration.srt_service.get_settings", return_value=settings):
                output = create_full_srt(project, [segment])
                artifacts = read_alignment_outputs(project)

            self.assertTrue(output.is_file())
            self.assertIn(segment.text, output.read_text(encoding="utf-8"))
            self.assertEqual(artifacts["alignment"]["mode"], "heuristic_fallback")
            self.assertFalse(artifacts["qa"]["passed"])
            self.assertEqual(artifacts["qa"]["review_count"], 1)


if __name__ == "__main__":
    unittest.main()
