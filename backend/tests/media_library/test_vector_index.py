import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.integrations.vision import vector_index
from app.integrations.vision.embedding import MODEL_NAME, VECTOR_DIMENSIONS


class VectorIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name) / "workspace"
        self.settings = SimpleNamespace(workspace_dir=self.workspace)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_faiss_index_upserts_searches_and_removes_shots(self) -> None:
        airport = _unit_vector(0)
        mountain = _unit_vector(1)
        with (
            patch.object(vector_index, "get_settings", return_value=self.settings),
            patch.object(vector_index, "embed_media", side_effect=[airport, mountain]),
            patch.object(vector_index, "embed_text", return_value=airport),
        ):
            airport_id = vector_index.upsert_shot("airport", "airport", ["unused"])
            mountain_id = vector_index.upsert_shot("mountain", "mountain", ["unused"])
            scores = vector_index.search("airport query")
            vector_index.remove_shot("airport")
            after_remove = vector_index.search("airport query")

        self.assertNotEqual(airport_id, mountain_id)
        self.assertEqual(scores["airport"], 1.0)
        self.assertEqual(scores["mountain"], 0.0)
        self.assertNotIn("airport", after_remove)
        self.assertTrue(
            (self.workspace / "indexes" / f"{vector_index.INDEX_BASENAME}.faiss").is_file()
        )
        metadata = json.loads(
            (
                self.workspace / "indexes" / f"{vector_index.INDEX_BASENAME}.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["model"], MODEL_NAME)
        self.assertNotIn("vector", metadata["vectors"][str(mountain_id)])

    def test_upsert_reuses_vector_id_and_replaces_vector(self) -> None:
        first = _unit_vector(0)
        replacement = _unit_vector(2)
        with (
            patch.object(vector_index, "get_settings", return_value=self.settings),
            patch.object(vector_index, "embed_media", side_effect=[first, replacement]),
            patch.object(vector_index, "embed_text", return_value=replacement),
        ):
            original_id = vector_index.upsert_shot("same-shot", "first")
            replacement_id = vector_index.upsert_shot("same-shot", "replacement")
            scores = vector_index.search("replacement")

        self.assertEqual(original_id, replacement_id)
        self.assertEqual(scores["same-shot"], 1.0)


def _unit_vector(index: int) -> list[float]:
    vector = [0.0] * VECTOR_DIMENSIONS
    vector[index] = 1.0
    return vector


if __name__ == "__main__":
    unittest.main()
