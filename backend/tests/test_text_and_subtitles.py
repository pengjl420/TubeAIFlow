import unittest

from app.services.segmenter import split_script
from app.services.subtitle_splitter import split_timed_subtitle_cues
from app.services.text_cleaner import clean_script
from app.utils.time_utils import seconds_to_ass_time, seconds_to_srt_time


class TextServiceTests(unittest.TestCase):
    def test_clean_script_normalizes_markdown_and_ellipsis(self) -> None:
        self.assertEqual(clean_script("# 标题\r\n\r\n- 内容......"), "标题\n内容。。")

    def test_split_script_preserves_all_text_and_limits_long_segments(self) -> None:
        text = "第一句。" + "很长的内容，" * 30 + "结束。"
        segments = split_script(text, min_len=20, max_len=40)

        self.assertEqual("".join(item["text_zh"] for item in segments), text)
        self.assertTrue(all(len(item["text_zh"]) <= 40 for item in segments))
        self.assertEqual([item["segment_id"] for item in segments], [f"{i:04d}" for i in range(1, len(segments) + 1)])

    def test_subtitle_cues_are_contiguous_and_cover_full_duration(self) -> None:
        cues = split_timed_subtitle_cues("这是第一句，这是第二句，这是第三句。", 1.0, 5.0, "zh")

        self.assertEqual(cues[0][0], 1.0)
        self.assertEqual(cues[-1][1], 5.0)
        self.assertTrue(all(left[1] == right[0] for left, right in zip(cues, cues[1:])))


class TimeFormatTests(unittest.TestCase):
    def test_time_format_rounding(self) -> None:
        self.assertEqual(seconds_to_ass_time(3661.239), "1:01:01.24")
        self.assertEqual(seconds_to_srt_time(3661.239), "01:01:01,239")


if __name__ == "__main__":
    unittest.main()
