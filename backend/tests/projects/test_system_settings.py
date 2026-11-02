import unittest
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.config import Settings
from app.services.settings.system_settings_service import (
    SECRET_FIELDS,
    _serialize_settings,
    _validate_paths,
    get_public_settings,
)


class SettingsModelTests(unittest.TestCase):
    def test_engine_host_is_clamped_to_loopback(self) -> None:
        self.assertEqual(Settings(app_host="0.0.0.0").app_host, "127.0.0.1")
        self.assertEqual(Settings(app_host="192.168.1.20").app_host, "127.0.0.1")
        self.assertEqual(Settings(app_host="localhost").app_host, "localhost")

    def test_empty_optional_paths_become_none(self) -> None:
        settings = Settings(
            qwen_tts_root="",
            qwen_tts_python="  ",
            cosyvoice_root="",
        )
        self.assertIsNone(settings.qwen_tts_root)
        self.assertIsNone(settings.qwen_tts_python)
        self.assertIsNone(settings.cosyvoice_root)

    def test_local_model_dtypes_are_validated(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported Qwen3-TTS dtype"):
            Settings(qwen_tts_dtype="int8")
        self.assertEqual(
            Settings(image_generation_provider_id="image.local_sdxl").image_generation_provider_id,
            "image.seedream_5",
        )
        self.assertEqual(
            Settings(
                image_generation_provider_id="image.seedream_5_flash"
            ).image_generation_provider_id,
            "image.seedream_5_flash",
        )

    def test_subtitle_duration_range_is_validated(self) -> None:
        with self.assertRaisesRegex(ValueError, "Minimum subtitle cue duration"):
            Settings(subtitle_min_cue_duration_ms=5000, subtitle_max_cue_duration_ms=5000)

    def test_storyboard_transition_defaults_total_one_hundred(self) -> None:
        settings = Settings()
        self.assertEqual(
            sum(item.percentage for item in settings.storyboard_transition_effects if item.enabled),
            100,
        )

    def test_public_settings_never_expose_secret_values(self) -> None:
        configured = Settings(
            deepseek_api_key="secret",
            seedream_api_key="ark-secret",
            workspace_dir=Path("workspace"),
        )
        with patch(
            "app.services.settings.system_settings_service.get_settings", return_value=configured
        ):
            public = get_public_settings()
        self.assertEqual(SECRET_FIELDS, {"deepseek_api_key", "seedream_api_key"})
        self.assertEqual(public["deepseek_api_key"], "")
        self.assertTrue(public["deepseek_api_key_configured"])
        self.assertEqual(public["seedream_api_key"], "")
        self.assertTrue(public["seedream_api_key_configured"])

    def test_legacy_deepseek_model_is_migrated(self) -> None:
        self.assertEqual(
            Settings(deepseek_model="deepseek-chat").deepseek_model, "deepseek-v4-flash"
        )

    def test_saving_core_settings_preserves_optional_module_values(self) -> None:
        record = SimpleNamespace(
            config_json=json.dumps({"pexels_api_key": "provider-secret", "app_port": 1234})
        )

        serialized = json.loads(_serialize_settings(Settings(app_port=18080), record))

        self.assertEqual(serialized["app_port"], 18080)
        self.assertNotIn("pexels_api_key", serialized)

    def test_serialized_settings_never_contain_plaintext_secrets(self) -> None:
        serialized = json.loads(
            _serialize_settings(
                Settings(deepseek_api_key="secret"),
                None,
                {"deepseek_api_key": "settings-deepseek_api_key"},
            )
        )

        self.assertNotIn("deepseek_api_key", serialized)
        self.assertEqual(
            serialized["credential_refs"]["deepseek_api_key"],
            "settings-deepseek_api_key",
        )

    def test_premiere_path_must_reference_an_existing_file(self) -> None:
        settings = Settings(
            workspace_dir=Path("workspace"),
            premiere_pro_path=Path("missing-premiere.exe"),
        )
        with (
            patch.object(Path, "mkdir"),
            patch.object(Path, "is_dir", return_value=True),
            patch.object(Path, "is_file", return_value=False),
            self.assertRaisesRegex(ValueError, "premiere_pro_path"),
        ):
            _validate_paths(settings)


if __name__ == "__main__":
    unittest.main()
