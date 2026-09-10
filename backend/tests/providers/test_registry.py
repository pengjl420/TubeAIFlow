import unittest

from app.providers import (
    ProviderCapability,
    ProviderCategory,
    ImageProviderRuntime,
    TTSProviderRuntime,
    provider_registry,
)
from app.services.narration import tts_service  # noqa: F401 - binds executable adapters
from app.services.image_generation import image_generation_service  # noqa: F401


class ProviderRegistryTests(unittest.TestCase):
    def test_builtin_tts_providers_have_stable_qualified_ids(self) -> None:
        providers = provider_registry.list(ProviderCategory.TTS)

        self.assertEqual(
            {item.id for item in providers},
            {"tts.cosyvoice", "tts.index_tts", "tts.moss_tts", "tts.qwen3_tts"},
        )
        self.assertEqual(
            provider_registry.legacy_ids(ProviderCategory.TTS),
            {"cosyvoice", "index_tts", "moss_tts", "qwen3_tts"},
        )

    def test_legacy_provider_id_resolves_during_compatibility_period(self) -> None:
        provider = provider_registry.get("cosyvoice")

        self.assertEqual(provider.id, "tts.cosyvoice")
        self.assertIn(ProviderCapability.SPEED, provider.capabilities)

    def test_unknown_provider_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported provider"):
            provider_registry.get("tts.unknown")

    def test_builtin_tts_providers_have_executable_runtime_adapters(self) -> None:
        for provider in provider_registry.list(ProviderCategory.TTS):
            self.assertTrue(provider_registry.is_executable(provider.id))
            self.assertIsInstance(
                provider_registry.runtime(provider.id, TTSProviderRuntime),
                TTSProviderRuntime,
            )

    def test_local_image_provider_has_executable_runtime_adapter(self) -> None:
        image_generation_service.bind_builtin_provider_runtimes()
        providers = provider_registry.list(ProviderCategory.IMAGE)
        self.assertEqual([item.id for item in providers], ["image.local_sdxl"])
        self.assertIsInstance(
            provider_registry.runtime("image.local_sdxl", ImageProviderRuntime),
            ImageProviderRuntime,
        )


if __name__ == "__main__":
    unittest.main()
