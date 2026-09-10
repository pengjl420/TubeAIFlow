import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock

from app.providers import (
    ProviderCapability,
    ProviderCategory,
    ImageProviderRuntime,
    ImageBatchRequest,
    ProviderBillingMode,
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

    def test_local_provider_cost_contract_does_not_invent_cloud_cost(self) -> None:
        tts = provider_registry.runtime("tts.cosyvoice", TTSProviderRuntime)
        estimate = tts.estimate_cost(character_count=1234)

        self.assertEqual(estimate.billing, ProviderBillingMode.LOCAL)
        self.assertEqual(estimate.estimated_usd, 0)
        self.assertEqual(estimate.usage, {"characters": 1234})

    def test_image_provider_health_reports_missing_local_assets(self) -> None:
        runtime = ImageProviderRuntime(generate_batch=Mock())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = ImageBatchRequest(
                project_id="p1",
                jobs=({}, {}),
                batch_path=root / "batch.json",
                result_path=root / "result.json",
                progress_path=root / "progress.json",
                python_path=root / "missing-python.exe",
                model_path=root / "missing-model.safetensors",
                config_dir=root / "missing-config",
                device="cpu",
                dtype="float32",
                cpu_offload=False,
            )

            health = runtime.health_check(request)
            estimate = runtime.estimate_cost(request)

        self.assertFalse(health.available)
        self.assertIn("missing-python.exe", health.error or "")
        self.assertEqual(estimate.billing, ProviderBillingMode.LOCAL)
        self.assertEqual(estimate.usage, {"images": 2})


if __name__ == "__main__":
    unittest.main()
