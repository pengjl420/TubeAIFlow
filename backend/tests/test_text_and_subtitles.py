import unittest

from app.services.segmenter import split_script
from app.services.subtitle_splitter import split_timed_subtitle_cues, wrap_subtitle_text
from app.services.text_cleaner import clean_script
from app.services.translate_service import detect_text_language
from app.utils.time_utils import seconds_to_ass_time, seconds_to_srt_time


class TextServiceTests(unittest.TestCase):
    def test_clean_script_normalizes_markdown_and_ellipsis(self) -> None:
        self.assertEqual(clean_script("# 标题\r\n\r\n- 内容......"), "标题\n内容。。")

    def test_split_script_uses_non_empty_lines_as_segments(self) -> None:
        text = "第一段，包含多个标点。仍然属于第一段！\r\n\r\n  第二段很短  \n第三段没有句号"

        segments = split_script(text)

        self.assertEqual(
            [item["text_zh"] for item in segments],
            ["第一段，包含多个标点。仍然属于第一段！", "第二段很短", "第三段没有句号"],
        )
        self.assertEqual([item["segment_id"] for item in segments], ["0001", "0002", "0003"])
        self.assertEqual([item["index"] for item in segments], [1, 2, 3])

    def test_split_script_does_not_split_long_lines(self) -> None:
        long_line = "很长的内容，" * 30 + "结束。"

        segments = split_script(long_line)

        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0]["text_zh"], long_line)

    def test_subtitle_cues_are_contiguous_and_cover_full_duration(self) -> None:
        cues = split_timed_subtitle_cues("这是第一句，这是第二句，这是第三句。", 1.0, 5.0, "zh")

        self.assertEqual(cues[0][0], 1.0)
        self.assertEqual(cues[-1][1], 5.0)
        self.assertTrue(all(left[1] == right[0] for left, right in zip(cues, cues[1:])))

    def test_display_wrapping_never_truncates_english_words(self) -> None:
        text = "This deliberately long English subtitle must preserve every word even when it wraps onto more than two display lines."

        wrapped = wrap_subtitle_text(text, "en")

        self.assertEqual(wrapped.replace("\n", " "), text)

    def test_translation_direction_uses_transcript_language(self) -> None:
        self.assertEqual(detect_text_language("这是一份中文逐字稿"), "zh")
        self.assertEqual(detect_text_language("This is an English transcript."), "en")


class TimeFormatTests(unittest.TestCase):
    def test_time_format_rounding(self) -> None:
        self.assertEqual(seconds_to_ass_time(3661.239), "1:01:01.24")
        self.assertEqual(seconds_to_srt_time(3661.239), "01:01:01,239")


if __name__ == "__main__":
    unittest.main()
