import unittest

from app.models.narration import Segment
from app.services.narration.subtitle_service import build_segment_cues, display_units
from app.services.narration.srt_service import _clean_srt_text


class SrtServiceTests(unittest.TestCase):
    def test_clean_srt_text_preserves_source_punctuation(self) -> None:
        text = "你好，世界！This is a test: yes/no?（确认）\n第二行……"

        self.assertEqual(_clean_srt_text(text), text)

    def test_clean_srt_text_keeps_letters_numbers_and_line_breaks(self) -> None:
        text = "第 1 集\r\nAI 2026"

        self.assertEqual(_clean_srt_text(text), "第 1 集\nAI 2026")

    def test_long_segment_is_split_into_continuous_readable_cues(self) -> None:
        text = "这是第一句用于测试字幕拆分。这里是第二句，内容同样需要保持完整。最后一句用于确认时间轴连续。"
        segment = Segment(
            id="project-1:segment-1",
            project_id="project-1",
            segment_id="0001",
            segment_index=1,
            text=text,
            duration=12.0,
            start_time=0.0,
            end_time=12.0,
        )

        cues = build_segment_cues("project-1", [segment], max_display_units=22)

        self.assertGreaterEqual(len(cues), 3)
        self.assertEqual("".join(cue["text"] for cue in cues), text)
        self.assertEqual(cues[0]["start_ms"], 0)
        self.assertEqual(cues[-1]["end_ms"], 12_000)
        self.assertTrue(
            all(
                cues[index]["end_ms"] == cues[index + 1]["start_ms"]
                for index in range(len(cues) - 1)
            )
        )
        self.assertTrue(all(cue["source_segment_id"] == segment.id for cue in cues))
        self.assertEqual([cue["cue_index"] for cue in cues], list(range(1, len(cues) + 1)))
        self.assertTrue(all(display_units(cue["text"]) <= 22 for cue in cues))

    def test_short_audio_merges_chunks_that_cannot_meet_minimum_duration(self) -> None:
        segment = Segment(
            id="project-1:segment-1",
            project_id="project-1",
            segment_id="0001",
            segment_index=1,
            text="第一小句，第二小句，第三小句。",
            duration=1.5,
        )

        cues = build_segment_cues(
            "project-1",
            [segment],
            max_display_units=6,
            min_duration_ms=1000,
        )

        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0]["text"], segment.text)
        self.assertEqual((cues[0]["start_ms"], cues[0]["end_ms"]), (0, 1500))

    def test_slow_short_text_is_split_to_avoid_an_overlong_cue(self) -> None:
        segment = Segment(
            id="project-1:segment-1",
            project_id="project-1",
            segment_id="0001",
            segment_index=1,
            text="这是一句语速很慢的完整配音。",
            duration=12.0,
        )

        cues = build_segment_cues(
            "project-1",
            [segment],
            max_display_units=22,
            max_duration_ms=6000,
        )

        self.assertEqual(len(cues), 2)
        self.assertEqual("".join(cue["text"] for cue in cues), segment.text)
        self.assertTrue(all(cue["end_ms"] - cue["start_ms"] <= 6000 for cue in cues))


if __name__ == "__main__":
    unittest.main()
