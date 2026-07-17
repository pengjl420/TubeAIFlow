import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.infrastructure import gpu_resource
from app.integrations.vision import embedding


class EmbeddingGpuGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        settings = type(
            "Settings",
            (),
            {"workspace_dir": Path(self.temp_dir.name)},
        )()
        self.settings_patch = patch.object(gpu_resource, "get_settings", return_value=settings)
        self.settings_patch.start()

    def tearDown(self) -> None:
        self.settings_patch.stop()
        self.temp_dir.cleanup()

    def test_embedding_model_is_released_after_standalone_inference(self) -> None:
        runtime = Mock()
        runtime.embed.return_value = [1.0]
        with (
            patch.object(embedding, "_get_runtime", return_value=runtime),
            patch.object(embedding, "release_model") as release_model,
        ):
            result = embedding.embed_text("airport")

        self.assertEqual(result, [1.0])
        release_model.assert_called_once_with()

    def test_embedding_model_is_released_even_when_inference_fails(self) -> None:
        runtime = Mock()
        runtime.embed.side_effect = RuntimeError("inference failed")
        with (
            patch.object(embedding, "_get_runtime", return_value=runtime),
            patch.object(embedding, "release_model") as release_model,
        ):
            with self.assertRaisesRegex(RuntimeError, "inference failed"):
                embedding.embed_text("airport")

        release_model.assert_called_once_with()

    def test_business_lease_reuses_model_and_releases_once(self) -> None:
        runtime = Mock()
        runtime.embed.return_value = [1.0]
        with (
            patch.object(embedding, "_get_runtime", return_value=runtime),
            patch.object(embedding, "release_model") as release_model,
            gpu_resource.exclusive_gpu("asset-vectorization"),
        ):
            embedding.embed_text("airport")
            embedding.embed_text("traveler")
            release_model.assert_not_called()

        self.assertEqual(runtime.embed.call_count, 2)
        release_model.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
