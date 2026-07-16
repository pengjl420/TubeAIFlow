import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.models.project import Project
from app.services.narration import translation_service as translate_service
from app.services.narration.srt_service import _write_srt, build_chinese_subtitle_cues, create_english_srt_from_chinese_cues
from app.services.narration.translation_service import (
    _parse_cue_translation_response,
    _parse_complete_translation_batch,
    _parse_deepseek_json_content,
    _parse_translation_response,
    _request_deepseek_json,
    _translate_cue_batch,
)


class TranslationServiceTests(unittest.TestCase):
    def test_parse_translation_response_returns_segment_mapping(self) -> None:
        data = {
            "translations": [
                {"segment_id": "0001", "text_en": "Hello world."},
                {"segment_id": "0002", "text_en": "Keep the same timing."},
            ]
        }

        self.assertEqual(
            _parse_translation_response(data),
            {
                "0001": "Hello world.",
                "0002": "Keep the same timing.",
            },
        )

    def test_parse_cue_translation_response_returns_cue_mapping(self) -> None:
        data = {
            "translations": [
                {"cue_id": "0001", "text_en": "First subtitle."},
                {"cue_id": "0002", "text_en": "Second subtitle."},
            ]
        }

        self.assertEqual(
            _parse_cue_translation_response(data),
            {
                "0001": "First subtitle.",
                "0002": "Second subtitle.",
            },
        )

    def test_parse_cue_translation_response_accepts_top_level_list(self) -> None:
        data = [
            {"cue_id": "0001", "translation": "First subtitle."},
            {"cue_id": "0002", "translation": "Second subtitle."},
        ]

        self.assertEqual(
            _parse_cue_translation_response(data),
            {
                "0001": "First subtitle.",
                "0002": "Second subtitle.",
            },
        )

    def test_parse_cue_translation_response_accepts_nested_results(self) -> None:
        data = {
            "result": {
                "items": [
                    {"id": "0001", "english": "First subtitle."},
                    {"id": "0002", "english": "Second subtitle."},
                ]
            }
        }

        self.assertEqual(
            _parse_cue_translation_response(data),
            {
                "0001": "First subtitle.",
                "0002": "Second subtitle.",
            },
        )

    def test_parse_cue_translation_response_accepts_id_text_mapping(self) -> None:
        data = {
            "0001": "First subtitle.",
            "0002": "Second subtitle.",
        }

        self.assertEqual(
            _parse_cue_translation_response(data),
            {
                "0001": "First subtitle.",
                "0002": "Second subtitle.",
            },
        )

    def test_parse_cue_translation_response_accepts_translations_mapping(self) -> None:
        data = {
            "translations": {
                "0001": {"text_en": "First subtitle."},
                "0002": {"translated_text": "Second subtitle."},
            }
        }

        self.assertEqual(
            _parse_cue_translation_response(data),
            {
                "0001": "First subtitle.",
                "0002": "Second subtitle.",
            },
        )

    def test_parse_cue_translation_response_accepts_subtitles_key(self) -> None:
        data = {
            "subtitles": [
                {"cue_id": "0001", "text": "First subtitle."},
                {"cue_id": "0002", "text": "Second subtitle."},
            ]
        }

        self.assertEqual(
            _parse_cue_translation_response(data),
            {
                "0001": "First subtitle.",
                "0002": "Second subtitle.",
            },
        )

    def test_parse_cue_translation_response_accepts_prefixed_id_mapping(self) -> None:
        data = {
            "translations": {
                "cue_0001": "First subtitle.",
                "cue-0002": "Second subtitle.",
            }
        }

        self.assertEqual(
            _parse_cue_translation_response(data),
            {
                "0001": "First subtitle.",
                "0002": "Second subtitle.",
            },
        )

    def test_parse_cue_translation_response_accepts_single_nested_item(self) -> None:
        data = {
            "translations": {
                "cue_id": "0001",
                "text_en": "First subtitle.",
            }
        }

        self.assertEqual(
            _parse_cue_translation_response(data),
            {"0001": "First subtitle."},
        )

    @patch("app.services.narration.translation_service.httpx.post")
    @patch("app.services.narration.translation_service.get_settings")
    def test_request_retries_after_schema_mismatch(self, get_settings: Mock, post: Mock) -> None:
        get_settings.return_value = SimpleNamespace(
            deepseek_base_url="https://api.deepseek.com",
            deepseek_api_key="test-key",
            translation_timeout_seconds=60,
            translation_retry_count=1,
        )
        invalid_response = Mock()
        invalid_response.raise_for_status.return_value = None
        invalid_response.json.return_value = {
            "id": "first",
            "model": "test-model",
            "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
            "usage": {},
        }
        valid_response = Mock()
        valid_response.raise_for_status.return_value = None
        valid_response.json.return_value = {
            "id": "second",
            "model": "test-model",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": '{"translations":[{"cue_id":"0001","text_en":"Hello."}]}'
                    },
                }
            ],
            "usage": {},
        }
        post.side_effect = [invalid_response, valid_response]
        payload = {
            "messages": [{"role": "system", "content": "Return JSON."}],
            "temperature": 0.2,
        }

        result = _request_deepseek_json(
            payload,
            "subtitle translation",
            1,
            1,
            None,
            _parse_cue_translation_response,
        )

        self.assertEqual(result, {"0001": "Hello."})
        self.assertEqual(post.call_count, 2)
        retry_payload = post.call_args_list[1].kwargs["json"]
        self.assertEqual(retry_payload["temperature"], 0)
        self.assertIn("Previous output could not be parsed", retry_payload["messages"][0]["content"])

    @patch("app.services.narration.translation_service.httpx.post")
    @patch("app.services.narration.translation_service.get_settings")
    def test_request_retries_when_batch_omits_a_cue(self, get_settings: Mock, post: Mock) -> None:
        get_settings.return_value = SimpleNamespace(
            deepseek_base_url="https://api.deepseek.com",
            deepseek_api_key="test-key",
            translation_timeout_seconds=60,
            translation_retry_count=1,
        )
        first_response = Mock()
        first_response.raise_for_status.return_value = None
        first_response.json.return_value = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": '{"translations":[{"cue_id":"0001","text_en":"First."}]}'
                    },
                }
            ]
        }
        second_response = Mock()
        second_response.raise_for_status.return_value = None
        second_response.json.return_value = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": (
                            '{"translations":['
                            '{"cue_id":"0001","text_en":"First."},'
                            '{"cue_id":"0002","text_en":"Second."}'
                            "]}"
                        )
                    },
                }
            ]
        }
        post.side_effect = [first_response, second_response]

        result = _request_deepseek_json(
            {"messages": [{"role": "system", "content": "Return JSON."}]},
            "subtitle translation",
            1,
            2,
            None,
            lambda data: _parse_complete_translation_batch(
                data,
                _parse_cue_translation_response,
                ["0001", "0002"],
                "subtitle cue",
            ),
        )

        self.assertEqual(result, {"0001": "First.", "0002": "Second."})
        self.assertEqual(post.call_count, 2)

    @patch("app.services.narration.translation_service._translate_cue_batch")
    @patch("app.services.narration.translation_service.get_settings")
    def test_cue_translation_is_split_into_configured_batches(
        self,
        get_settings: Mock,
        translate_batch: Mock,
    ) -> None:
        get_settings.return_value = SimpleNamespace(translation_batch_size=30)
        translate_batch.side_effect = lambda cues, *_: {
            cue["cue_id"]: f"English {cue['cue_id']}" for cue in cues
        }
        cues = [
            {"cue_id": f"{index:04d}", "text_zh": f"Chinese {index}"}
            for index in range(1, 66)
        ]

        result = translate_service._translate_cues_with_deepseek(cues)

        self.assertEqual(len(result), 65)
        self.assertEqual([len(call.args[0]) for call in translate_batch.call_args_list], [30, 30, 5])

    @patch("app.services.narration.translation_service._request_deepseek_json")
    @patch("app.services.narration.translation_service.get_settings")
    def test_failed_cue_batch_is_split_and_retried(
        self,
        get_settings: Mock,
        request_json: Mock,
    ) -> None:
        get_settings.return_value = SimpleNamespace(
            deepseek_model="test-model",
            translation_max_tokens=1000,
        )
        request_json.side_effect = [
            RuntimeError("incomplete batch"),
            {"0001": "First."},
            {"0002": "Second."},
        ]
        cues = [
            {"cue_id": "0001", "text_zh": "第一条"},
            {"cue_id": "0002", "text_zh": "第二条"},
        ]

        result = _translate_cue_batch(cues, 1, None)

        self.assertEqual(result, {"0001": "First.", "0002": "Second."})
        self.assertEqual(request_json.call_count, 3)

    def test_parse_deepseek_json_content_accepts_markdown_fence(self) -> None:
        content = """```json
{"translations": [{"cue_id": "0001", "text_en": "First subtitle."}]}
```"""

        self.assertEqual(
            _parse_deepseek_json_content(content),
            {"translations": [{"cue_id": "0001", "text_en": "First subtitle."}]},
        )

    def test_parse_deepseek_json_content_extracts_embedded_object(self) -> None:
        content = (
            "Here is the JSON:\n"
            '{"translations": [{"segment_id": "0001", "text_en": "Hello."}]}\n'
            "Done."
        )

        self.assertEqual(
            _parse_deepseek_json_content(content),
            {"translations": [{"segment_id": "0001", "text_en": "Hello."}]},
        )


class EnglishSrtTests(unittest.TestCase):
    def test_each_audio_segment_creates_exactly_one_subtitle_cue(self) -> None:
        segments = [
            SimpleNamespace(
                segment_id="0001",
                text_zh="Shanghai's career-defining public offering.",
                duration=3.25,
            ),
            SimpleNamespace(
                segment_id="0002",
                text_zh="A second line stays in one subtitle cue.",
                duration=2.5,
            ),
        ]

        cues = build_chinese_subtitle_cues(segments)

        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0]["cue_id"], "0001")
        self.assertEqual(cues[0]["start"], 0.0)
        self.assertEqual(cues[0]["end"], 3.25)
        self.assertEqual(cues[0]["text_zh"], "Shanghai's career-defining public offering.")
        self.assertEqual(cues[1]["start"], 3.25)
        self.assertEqual(cues[1]["end"], 5.75)

    def test_chinese_cues_skip_text_that_is_empty_after_cleaning(self) -> None:
        segments = [
            SimpleNamespace(
                segment_id="0001",
                text_zh="第一句。、第二句。",
                duration=2.0,
            )
        ]

        cues = build_chinese_subtitle_cues(segments)

        self.assertTrue(cues)
        self.assertTrue(all(cue["text_zh"].strip() for cue in cues))
        self.assertEqual([cue["cue_id"] for cue in cues], [f"{index:04d}" for index in range(1, len(cues) + 1)])

    def test_english_srt_keeps_punctuation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "en.srt"

            _write_srt(path, [(0.0, 1.25, "Hello, world!")], remove_punctuation=False)

            self.assertEqual(
                path.read_text(encoding="utf-8"),
                "1\n00:00:00,000 --> 00:00:01,250\nHello, world!\n",
            )

    def test_english_srt_uses_chinese_cue_timestamps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Project(
                id="p1",
                name="demo",
                output_dir=temp_dir,
                config_json='{"output_filename": "demo"}',
            )
            zh_cues = [
                {"cue_id": "0001", "segment_id": "0001", "start": 0.0, "end": 1.25, "text_zh": "第一句"},
                {"cue_id": "0002", "segment_id": "0001", "start": 1.25, "end": 3.5, "text_zh": "第二句"},
            ]
            translations = {
                "0001": "First sentence.",
                "0002": "Second sentence.",
            }

            path = create_english_srt_from_chinese_cues(project, zh_cues, translations)

            self.assertEqual(
                path.read_text(encoding="utf-8"),
                "1\n00:00:00,000 --> 00:00:01,250\nFirst sentence.\n\n"
                "2\n00:00:01,250 --> 00:00:03,500\nSecond sentence.\n",
            )


if __name__ == "__main__":
    unittest.main()
