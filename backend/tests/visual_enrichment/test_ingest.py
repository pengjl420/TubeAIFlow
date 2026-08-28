import unittest

from app.services.visual_enrichment.ingest import build_canonical_timeline, normalize_transcript, parse_srt


SRT = """1
00:00:00,000 --> 00:00:02,500
第一句话。

2
00:00:02,500 --> 00:00:05,000
第二句话！
"""


class IngestTests(unittest.TestCase):
    def test_parse_and_align_srt(self) -> None:
        cues = parse_srt(SRT)
        self.assertEqual((cues[0].start_ms, cues[-1].end_ms), (0, 5000))
        timeline = build_canonical_timeline("第一句话。第二句话！", SRT)
        self.assertEqual([item.segment_id for item in timeline], ["sub_000001", "sub_000002"])
        self.assertLess(timeline[0].transcript_span.char_end, timeline[1].transcript_span.char_end)

    def test_normalization_ignores_case_width_space_and_punctuation(self) -> None:
        self.assertEqual(normalize_transcript("Ａ B，测试！"), "ab测试")

    def test_rejects_overlapping_cues(self) -> None:
        invalid = SRT.replace("00:00:02,500 --> 00:00:05,000", "00:00:02,000 --> 00:00:05,000")
        with self.assertRaisesRegex(ValueError, "overlaps"):
            parse_srt(invalid)
