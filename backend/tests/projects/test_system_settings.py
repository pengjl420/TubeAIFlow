import unittest
from pathlib import Path

from app.config import Settings
from app.infrastructure.asset_layout import media_preview_dir, provider_download_dir
from app.services.settings.system_settings_service import SECRET_FIELDS, get_public_settings
from unittest.mock import patch


class SettingsModelTests(unittest.TestCase):
    def test_empty_optional_paths_become_none(self) -> None:
        settings = Settings(
            qwen_tts_root="",
            qwen_tts_python="  ",
            qwen_tts_model_dir=None,
            cosyvoice_root="",
            cosyvoice_python="  ",
            cosyvoice_model_dir=None,
            vision_embedding_model_dir="",
            image_generation_model_path="",
            image_generation_config_dir="",
            image_generation_python="",
        )
        self.assertIsNone(settings.qwen_tts_root)
        self.assertIsNone(settings.qwen_tts_python)
        self.assertIsNone(settings.qwen_tts_model_dir)
        self.assertIsNone(settings.cosyvoice_root)
        self.assertIsNone(settings.cosyvoice_python)
        self.assertIsNone(settings.cosyvoice_model_dir)
        self.assertIsNone(settings.vision_embedding_model_dir)
        self.assertIsNone(settings.image_generation_model_path)
        self.assertIsNone(settings.image_generation_config_dir)
        self.assertIsNone(settings.image_generation_python)

    def test_qwen_dtype_is_validated(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported Qwen3-TTS dtype"):
            Settings(qwen_tts_dtype="int8")

    def test_vision_embedding_dtype_is_validated(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported vision embedding dtype"):
            Settings(vision_embedding_dtype="int8")

    def test_image_generation_dtype_is_validated(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported image generation dtype"):
            Settings(image_generation_dtype="int8")

    def test_media_search_cache_cannot_be_shorter_than_24_hours(self) -> None:
        with self.assertRaises(ValueError):
            Settings(media_search_cache_hours=23)

    def test_empty_provider_storage_paths_use_defaults(self) -> None:
        settings = Settings(pexels_storage_dir="", pixabay_storage_dir="  ")

        self.assertIsNone(settings.pexels_storage_dir)
        self.assertIsNone(settings.pixabay_storage_dir)

    def test_provider_storage_contains_downloads_and_previews(self) -> None:
        root = Path("D:/media/pexels")
        settings = Settings(workspace_dir=Path("D:/workspace"), pexels_storage_dir=root)

        self.assertEqual(provider_download_dir("pexels", settings), root)
        self.assertEqual(
            media_preview_dir("media_1", "pexels", settings),
            root / "thumbnails" / "media_1",
        )

    def test_unconfigured_provider_keeps_existing_default_layout(self) -> None:
        workspace = Path("D:/workspace")
        settings = Settings(workspace_dir=workspace)

        self.assertEqual(
            provider_download_dir("pixabay", settings),
            workspace / "assets" / "downloads" / "pixabay",
        )
        self.assertEqual(
            media_preview_dir("media_2", "pixabay", settings),
            workspace / "assets" / "media_2",
        )

    def test_storyboard_transition_defaults_are_configurable(self) -> None:
        settings = Settings()

        self.assertEqual(
            [item.name for item in settings.storyboard_transition_effects],
            ["fade", "dissolve", "fadeblack", "smoothleft", "smoothright"],
        )
        self.assertEqual(
            sum(item.percentage for item in settings.storyboard_transition_effects if item.enabled),
            100,
        )
        self.assertEqual(settings.storyboard_transition_group_min_clips, 2)
        self.assertEqual(settings.storyboard_transition_group_max_clips, 5)
        self.assertEqual(settings.storyboard_transition_min_per_group, 1)
        self.assertEqual(settings.storyboard_transition_max_per_group, 2)
        self.assertEqual(settings.storyboard_transition_duration_seconds, 0.45)

    def test_landscape_transition_percentages_must_total_one_hundred(self) -> None:
        with self.assertRaisesRegex(ValueError, "must total 100"):
            Settings(
                storyboard_transition_effects=[
                    {"name": "fade", "enabled": True, "percentage": 40},
                    {"name": "dissolve", "enabled": True, "percentage": 20},
                    {"name": "fadeblack", "enabled": True, "percentage": 10},
                    {"name": "smoothleft", "enabled": True, "percentage": 10},
                    {"name": "smoothright", "enabled": True, "percentage": 10},
                ]
            )

    def test_all_landscape_transitions_can_be_disabled(self) -> None:
        settings = Settings(
            storyboard_transition_effects=[
                {"name": name, "enabled": False, "percentage": percentage}
                for name, percentage in [
                    ("fade", 45),
                    ("dissolve", 25),
                    ("fadeblack", 10),
                    ("smoothleft", 10),
                    ("smoothright", 10),
                ]
            ]
        )

        self.assertFalse(any(item.enabled for item in settings.storyboard_transition_effects))

    def test_legacy_landscape_transition_settings_are_migrated(self) -> None:
        settings = Settings(
            landscape_transition_effects=[
                {"name": "fade", "enabled": True, "percentage": 100},
                {"name": "dissolve", "enabled": False, "percentage": 25},
                {"name": "fadeblack", "enabled": False, "percentage": 10},
                {"name": "smoothleft", "enabled": False, "percentage": 10},
                {"name": "smoothright", "enabled": False, "percentage": 10},
            ]
        )

        self.assertEqual(settings.storyboard_transition_effects[0].percentage, 100)

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
