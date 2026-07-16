import unittest
from pathlib import Path

from app.config import Settings
from app.services.settings.system_settings_service import SECRET_FIELDS, get_public_settings
from unittest.mock import patch


class SettingsModelTests(unittest.TestCase):
    def test_empty_optional_paths_become_none(self) -> None:
        settings = Settings(
            index_tts_root="",
            index_tts_python="  ",
            index_tts_model_dir=None,
            qwen_tts_root="",
            qwen_tts_python="  ",
            qwen_tts_model_dir=None,
        )
        self.assertIsNone(settings.index_tts_root)
        self.assertIsNone(settings.index_tts_python)
        self.assertIsNone(settings.index_tts_model_dir)
        self.assertIsNone(settings.qwen_tts_root)
        self.assertIsNone(settings.qwen_tts_python)
        self.assertIsNone(settings.qwen_tts_model_dir)

    def test_qwen_dtype_is_validated(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported Qwen3-TTS dtype"):
            Settings(qwen_tts_dtype="int8")

    def test_public_settings_never_expose_secret_values(self) -> None:
        configured = Settings(deepseek_api_key="secret", workspace_dir=Path("workspace"))
        with patch("app.services.settings.system_settings_service.get_settings", return_value=configured):
            public = get_public_settings()

        for field_name in SECRET_FIELDS:
            self.assertEqual(public[field_name], "")
        self.assertTrue(public["deepseek_api_key_configured"])

    def test_legacy_deepseek_model_is_migrated(self) -> None:
        settings = Settings(deepseek_model="deepseek-chat")
        self.assertEqual(settings.deepseek_model, "deepseek-v4-flash")


if __name__ == "__main__":
    unittest.main()
