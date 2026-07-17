import unittest

from app.services.narration.srt_service import _clean_srt_text


class SrtServiceTests(unittest.TestCase):
    def test_clean_srt_text_preserves_source_punctuation(self) -> None:
        text = "你好，世界！This is a test: yes/no?（确认）\n第二行……"

        self.assertEqual(_clean_srt_text(text), text)

    def test_clean_srt_text_keeps_letters_numbers_and_line_breaks(self) -> None:
        text = "第 1 集\r\nAI 2026"

        self.assertEqual(_clean_srt_text(text), "第 1 集\nAI 2026")


if __name__ == "__main__":
    unittest.main()
