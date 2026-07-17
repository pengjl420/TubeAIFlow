import unittest

from app.services.narration.segmenter import split_script
from app.services.narration.text_cleaner import clean_script
from app.shared.time import seconds_to_srt_time


class TextServiceTests(unittest.TestCase):
    def test_clean_script_normalizes_markdown_and_ellipsis(self) -> None:
        self.assertEqual(clean_script("# 标题\r\n\r\n- 内容......"), "标题\n内容。。")

    def test_split_script_uses_non_empty_lines_as_segments(self) -> None:
        text = "第一段，包含多个标点。仍然属于第一段！\r\n\r\n  第二段很短  \n第三段没有句号"

        segments = split_script(text)

        self.assertEqual(
            [item["text"] for item in segments],
            ["第一段，包含多个标点。仍然属于第一段！", "第二段很短", "第三段没有句号"],
        )
        self.assertEqual([item["segment_id"] for item in segments], ["0001", "0002", "0003"])
        self.assertEqual([item["index"] for item in segments], [1, 2, 3])

    def test_split_script_does_not_split_long_lines(self) -> None:
        long_line = "很长的内容，" * 30 + "结束。"

        segments = split_script(long_line)

        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0]["text"], long_line)

class TimeFormatTests(unittest.TestCase):
    def test_time_format_rounding(self) -> None:
        self.assertEqual(seconds_to_srt_time(3661.239), "01:01:01,239")


if __name__ == "__main__":
    unittest.main()
