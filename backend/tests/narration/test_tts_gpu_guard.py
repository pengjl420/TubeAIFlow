import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from app.models.project import Project
from app.services.narration import tts_service


class TtsGpuGuardTests(unittest.TestCase):
    def test_tts_runner_executes_inside_exclusive_gpu_lease(self) -> None:
        events = []

        @contextmanager
        def fake_exclusive(owner: str):
            events.append(("acquired", owner))
            yield
            events.append(("released", owner))

        def fake_runner(*_args) -> None:
            events.append(("runner", "qwen3_tts"))

        project = Project(id="gpu-project", name="GPU project")
        with (
            tempfile.TemporaryDirectory() as root,
            patch.object(tts_service.gpu_resource, "exclusive_gpu", new=fake_exclusive),
            patch.object(tts_service, "_run_qwen3_tts_batch", side_effect=fake_runner),
        ):
            directory = Path(root)
            tts_service._run_tts_batch(
                "qwen3_tts",
                project,
                directory / "reference.wav",
                [],
                directory / "audio",
                directory / "logs",
            )

        self.assertEqual(
            events,
            [
                ("acquired", "tts:qwen3_tts:project:gpu-project"),
                ("runner", "qwen3_tts"),
                ("released", "tts:qwen3_tts:project:gpu-project"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
