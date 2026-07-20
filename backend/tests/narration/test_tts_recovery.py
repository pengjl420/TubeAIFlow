import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.integrations.tts import runner_io
from app.models.narration import Segment
from app.services.narration import tts_service


class TtsRecoveryTests(unittest.TestCase):
    def test_atomic_json_write_retries_transient_windows_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tts_progress.json"
            real_replace = runner_io.os.replace
            calls = 0

            def locked_once(source, target):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise PermissionError(5, "file is in use")
                return real_replace(source, target)

            with (
                patch.object(runner_io.os, "replace", side_effect=locked_once),
                patch.object(runner_io.time, "sleep") as sleep,
            ):
                runner_io.write_json(path, {"status": "running"})

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"status": "running"})
            self.assertEqual(calls, 2)
            sleep.assert_called_once()
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_recover_completed_segment_when_batch_text_and_audio_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio_dir = root / "audio"
            logs_dir = root / "logs"
            audio_dir.mkdir()
            logs_dir.mkdir()
            output_path = (audio_dir / "0001.wav").resolve()
            output_path.touch()
            (logs_dir / "tts_batch.json").write_text(
                json.dumps(
                    [{"segment_id": "0001", "text": "same text", "output_path": str(output_path)}]
                ),
                encoding="utf-8",
            )
            segment = Segment(
                id="p1_0001",
                project_id="p1",
                segment_id="0001",
                segment_index=1,
                text="same text",
            )
            session = Mock()

            with patch.object(tts_service, "probe_duration", return_value=2.5):
                recovered = tts_service._recover_completed_segments(
                    session, [segment], audio_dir, logs_dir
                )

            self.assertEqual(recovered, 1)
            self.assertEqual(segment.status, "completed")
            self.assertEqual(segment.duration, 2.5)
            self.assertEqual(segment.audio_path, str(output_path))
            session.add.assert_called_once_with(segment)
            session.commit.assert_called_once()

    def test_does_not_recover_audio_after_segment_text_changed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio_dir = root / "audio"
            logs_dir = root / "logs"
            audio_dir.mkdir()
            logs_dir.mkdir()
            output_path = (audio_dir / "0001.wav").resolve()
            output_path.touch()
            (logs_dir / "tts_batch.json").write_text(
                json.dumps(
                    [{"segment_id": "0001", "text": "old text", "output_path": str(output_path)}]
                ),
                encoding="utf-8",
            )
            segment = Segment(
                id="p1_0001",
                project_id="p1",
                segment_id="0001",
                segment_index=1,
                text="edited text",
            )
            session = Mock()

            recovered = tts_service._recover_completed_segments(
                session, [segment], audio_dir, logs_dir
            )

            self.assertEqual(recovered, 0)
            self.assertEqual(segment.status, "pending")
            session.add.assert_not_called()
            session.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
