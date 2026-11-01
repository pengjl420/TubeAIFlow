import json
import unittest

from app.integrations.llm.deepseek import ProviderOutputTruncatedError
from app.services.narration.segmenter import split_script, split_script_with_ai
from app.services.narration.text_cleaner import clean_script
from app.shared.time import seconds_to_srt_time


class TextServiceTests(unittest.TestCase):
    def test_ai_segmentation_preserves_content_without_redundant_visual_output(self) -> None:
        class FakeClient:
            def chat_json(self, _system_prompt: str, _user_prompt: str) -> dict:
                return {
                    "segments": [
                        {"text": "第一句。", "visual_description": "Opening scene"},
                        {"text": "第二句。", "visual_description": "Second scene"},
                    ]
                }

        segments = split_script_with_ai("第一句。\n第二句。", FakeClient())

        self.assertEqual([item["text"] for item in segments], ["第一句。", "第二句。"])
        self.assertNotIn("visual_description", segments[0])

    def test_ai_segmentation_rejects_rewritten_transcript(self) -> None:
        class FakeClient:
            def chat_json(self, _system_prompt: str, _user_prompt: str) -> dict:
                return {"segments": [{"text": "被改写的内容"}]}

        with self.assertRaisesRegex(ValueError, "修改、遗漏或重排"):
            split_script_with_ai("原始内容", FakeClient())

    def test_ai_segmentation_chunks_long_transcripts_and_preserves_content(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.calls = 0

            def chat_json(self, _system_prompt: str, user_prompt: str) -> dict:
                self.calls += 1
                window = json.loads(user_prompt)["script"]
                return {"segments": [{"text": window}]}

        client = FakeClient()
        script = "\n".join(f"Paragraph {index}: " + "word " * 80 for index in range(20))

        segments = split_script_with_ai(script, client)

        self.assertGreater(client.calls, 1)
        self.assertTrue(all(len(item["text"]) <= 180 for item in segments))
        self.assertEqual(
            "".join("".join(item["text"].split()) for item in segments),
            "".join(script.split()),
        )

    def test_ai_segmentation_falls_back_only_for_truncated_window(self) -> None:
        class FakeClient:
            def chat_json(self, _system_prompt: str, _user_prompt: str) -> dict:
                raise ProviderOutputTruncatedError("output truncated")

        script = "A complete sentence. " * 30
        segments = split_script_with_ai(script, FakeClient())

        self.assertGreater(len(segments), 1)
        self.assertEqual(
            "".join("".join(item["text"].split()) for item in segments),
            "".join(script.split()),
        )

    def test_ai_segmentation_uses_language_appropriate_guidance(self) -> None:
        prompts: list[str] = []

        class FakeClient:
            def chat_json(self, system_prompt: str, user_prompt: str) -> dict:
                prompts.append(system_prompt)
                return {"segments": [{"text": json.loads(user_prompt)["script"]}]}

        split_script_with_ai("This is a complete English narration sentence.", FakeClient())

        self.assertIn("15-35 words", prompts[0])

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

    def test_split_script_safely_splits_long_lines_without_rewriting(self) -> None:
        long_line = "很长的内容，" * 30 + "结束。"

        segments = split_script(long_line)

        self.assertGreater(len(segments), 1)
        self.assertTrue(all(len(item["text"]) <= 180 for item in segments))
        self.assertEqual("".join(item["text"] for item in segments), long_line)

    def test_split_script_bounds_a_sixty_minute_single_paragraph(self) -> None:
        sentence = "这是用于验证长视频稳定性的完整测试句子，包含自然停顿。"
        script = (sentence * 600)[:15_600]

        segments = split_script(script)

        self.assertGreater(len(segments), 60)
        self.assertTrue(all(1 <= len(item["text"]) <= 180 for item in segments))
        self.assertEqual("".join(item["text"] for item in segments), script)


class TimeFormatTests(unittest.TestCase):
    def test_time_format_rounding(self) -> None:
        self.assertEqual(seconds_to_srt_time(3661.239), "01:01:01,239")


if __name__ == "__main__":
    unittest.main()
