import tempfile
import unittest
from pathlib import Path

from app.services.visual_enrichment.storage import ArtifactStore, GenerationHistory


class StorageTests(unittest.TestCase):
    def test_artifact_hash_cache_detects_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = ArtifactStore(Path(temporary))
            path = store.write_json("work/value.json", {"value": 1})
            store.record_input_hash("work/value.json", "input-one")
            self.assertTrue(store.is_current("work/value.json", "input-one"))
            path.write_text('{"value": 2}', encoding="utf-8")
            self.assertFalse(store.is_current("work/value.json", "input-one"))

    def test_artifact_store_rejects_absolute_and_escaping_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = ArtifactStore(Path(temporary))
            with self.assertRaisesRegex(ValueError, "project-relative"):
                store.write_json(str(Path(temporary).resolve() / "outside.json"), {})
            with self.assertRaisesRegex(ValueError, "escapes project"):
                store.write_json("../outside.json", {})

    def test_generations_are_append_only_and_selection_moves(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            history = GenerationHistory(Path(temporary) / "pipeline.db")
            try:
                first = history.append(
                    project_id="p", generation_type="plan", provider="mock", model="m",
                    prompt="one", input_data={}, output_data={"v": 1}
                )
                second = history.append(
                    project_id="p", generation_type="plan", provider="mock", model="m",
                    prompt="two", input_data={}, output_data={"v": 2}
                )
                rows = history.versions("p", "plan")
            finally:
                history.close()
            self.assertEqual((first, second), (1, 2))
            self.assertEqual([row["is_selected"] for row in rows], [0, 1])
