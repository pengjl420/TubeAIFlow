import unittest

from app.providers import ProviderCapability, ProviderCategory, provider_registry


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


if __name__ == "__main__":
    unittest.main()
