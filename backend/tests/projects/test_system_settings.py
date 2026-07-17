import unittest
from pathlib import Path

from app.config import Settings
from app.services.settings.system_settings_service import SECRET_FIELDS, get_public_settings
from unittest.mock import patch


class SettingsModelTests(unittest.TestCase):
    def test_empty_optional_paths_become_none(self) -> None:
        settings = Settings(
            qwen_tts_root="",
            qwen_tts_python="  ",
            qwen_tts_model_dir=None,
            chatterbox_root="",
            chatterbox_python="  ",
            chatterbox_model_dir=None,
            cosyvoice_root="",
            cosyvoice_python="  ",
            cosyvoice_model_dir=None,
            vision_embedding_model_dir="",
        )
        self.assertIsNone(settings.qwen_tts_root)
        self.assertIsNone(settings.qwen_tts_python)
        self.assertIsNone(settings.qwen_tts_model_dir)
        self.assertIsNone(settings.chatterbox_root)
        self.assertIsNone(settings.chatterbox_python)
        self.assertIsNone(settings.chatterbox_model_dir)
        self.assertIsNone(settings.cosyvoice_root)
        self.assertIsNone(settings.cosyvoice_python)
        self.assertIsNone(settings.cosyvoice_model_dir)
        self.assertIsNone(settings.vision_embedding_model_dir)

    def test_qwen_dtype_is_validated(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported Qwen3-TTS dtype"):
            Settings(qwen_tts_dtype="int8")

    def test_chatterbox_model_version_is_validated(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported Chatterbox"):
            Settings(chatterbox_t3_model="v4")

    def test_vision_embedding_dtype_is_validated(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported vision embedding dtype"):
            Settings(vision_embedding_dtype="int8")

    def test_media_search_cache_cannot_be_shorter_than_24_hours(self) -> None:
        with self.assertRaises(ValueError):
            Settings(media_search_cache_hours=23)

    def test_public_settings_never_expose_secret_values(self) -> None:
        configured = Settings(
            deepseek_api_key="deepseek-secret",
            pexels_api_key="pexels-secret",
            pixabay_api_key="pixabay-secret",
            workspace_dir=Path("workspace"),
        )
        with patch("app.services.settings.system_settings_service.get_settings", return_value=configured):
            public = get_public_settings()

        for field_name in SECRET_FIELDS:
            self.assertEqual(public[field_name], "")
            self.assertTrue(public[f"{field_name}_configured"])

    def test_legacy_deepseek_model_is_migrated(self) -> None:
        settings = Settings(deepseek_model="deepseek-chat")
        self.assertEqual(settings.deepseek_model, "deepseek-v4-flash")


if __name__ == "__main__":
    unittest.main()
