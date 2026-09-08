import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services.settings import llm_model_manager


class LLMModelManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        llm_model_manager.reset_for_tests()

    def test_catalog_has_recommended_default_and_hardware_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = SimpleNamespace(
                workspace_dir=Path(directory) / "workspace",
                local_llm_models_dir=Path(directory) / "models",
            )
            with patch.object(llm_model_manager, "get_settings", return_value=settings):
                models = llm_model_manager.list_models()

        recommended = [item for item in models if item["recommended"]]
        self.assertEqual([item["id"] for item in recommended], ["qwen3-8b-q4_k_m"])
        self.assertTrue(all(item["size_bytes"] > 0 for item in models))
        self.assertTrue(all(item["recommended_vram_gb"] > 0 for item in models))

    def test_enqueue_is_idempotent_and_persists_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = SimpleNamespace(
                workspace_dir=Path(directory) / "workspace",
                local_llm_models_dir=Path(directory) / "models",
            )
            with (
                patch.object(llm_model_manager, "get_settings", return_value=settings),
                patch.object(llm_model_manager, "_ensure_worker"),
            ):
                first = llm_model_manager.enqueue_download("qwen3-8b-q4_k_m")
                second = llm_model_manager.enqueue_download("qwen3-8b-q4_k_m")

            self.assertEqual(first["id"], second["id"])
            self.assertEqual(first["status"], "queued")
            self.assertTrue(
                (settings.workspace_dir / "model_downloads" / "llm_downloads.json").is_file()
            )

    def test_installed_model_requires_gguf_header(self) -> None:
        spec = llm_model_manager.LLMModelSpec(
            id="tiny",
            display_name="Tiny",
            description="test",
            repo_id="test/tiny",
            filename="tiny.gguf",
            size_bytes=4,
            min_ram_gb=1,
            recommended_vram_gb=1,
            quality="fast",
        )
        with tempfile.TemporaryDirectory() as directory:
            settings = SimpleNamespace(local_llm_models_dir=Path(directory))
            target = Path(directory) / "tiny" / "tiny.gguf"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"GGUF")
            with patch.object(llm_model_manager, "get_settings", return_value=settings):
                self.assertEqual(llm_model_manager._installed_path(spec), target)


if __name__ == "__main__":
    unittest.main()
