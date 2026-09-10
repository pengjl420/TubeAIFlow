import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.models.narration import Segment
from app.models.project import Project
from app.services.narration import audio_service
from app.workflows import narration_generation


class SegmentOutputRefreshTests(unittest.TestCase):
    def test_existing_full_audio_is_rebuilt_without_subtitle_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            full_audio = Path(directory) / "full.wav"
            full_audio.touch()
            session = MagicMock()
            project = Project(id="p1", name="Project")
            segment = Segment(
                id="p1_0001",
                project_id="p1",
                segment_id="0001",
                segment_index=1,
                text="updated",
            )

            with (
                patch.object(
                    narration_generation,
                    "get_settings",
                    return_value=SimpleNamespace(workspace_dir=Path(directory)),
                ),
                patch.object(narration_generation, "get_final_audio_path", return_value=full_audio),
                patch.object(
                    narration_generation.tts_service, "regenerate_segment_tts", return_value=segment
                ) as regenerate,
                patch.object(narration_generation.audio_service, "merge_project_audio") as merge,
            ):
                result = narration_generation.regenerate_segment_and_refresh_outputs(
                    session, project, segment
                )

            self.assertIs(result, segment)
            regenerate.assert_called_once_with(session, project, segment)
            merge.assert_called_once_with(session, project)

    def test_outputs_are_not_created_when_full_audio_did_not_exist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            full_audio = Path(directory) / "full.wav"
            session = MagicMock()
            project = Project(id="p1", name="Project")
            segment = Segment(
                id="p1_0001",
                project_id="p1",
                segment_id="0001",
                segment_index=1,
                text="updated",
            )

            with (
                patch.object(
                    narration_generation,
                    "get_settings",
                    return_value=SimpleNamespace(workspace_dir=Path(directory)),
                ),
                patch.object(narration_generation, "get_final_audio_path", return_value=full_audio),
                patch.object(
                    narration_generation.tts_service, "regenerate_segment_tts", return_value=segment
                ),
                patch.object(narration_generation.audio_service, "merge_project_audio") as merge,
            ):
                narration_generation.regenerate_segment_and_refresh_outputs(
                    session, project, segment
                )

            merge.assert_not_called()


class AtomicAudioMergeTests(unittest.TestCase):
    def test_failed_merge_preserves_existing_full_audio(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "audio").mkdir()
            segment_audio = root / "0001.wav"
            segment_audio.write_bytes(b"segment")
            full_audio = root / "full.wav"
            full_audio.write_bytes(b"previous complete audio")
            segment = Segment(
                id="p1_0001",
                project_id="p1",
                segment_id="0001",
                segment_index=1,
                text="text",
                audio_path=str(segment_audio),
                duration=1.0,
                status="completed",
            )
            session = MagicMock()
            session.exec.return_value.all.return_value = [segment]
            project = Project(id="p1", name="Project")

            with (
                patch.object(
                    audio_service, "get_settings", return_value=SimpleNamespace(workspace_dir=root)
                ),
                patch.object(audio_service, "get_project_work_dir", return_value=root),
                patch.object(audio_service, "get_final_audio_path", return_value=full_audio),
                patch.object(audio_service, "ensure_project_dirs"),
                patch.object(audio_service, "run_ffmpeg", side_effect=RuntimeError("merge failed")),
            ):
                with self.assertRaisesRegex(RuntimeError, "merge failed"):
                    audio_service.merge_project_audio(session, project)

            self.assertEqual(full_audio.read_bytes(), b"previous complete audio")
            self.assertEqual(list(root.glob(".*.tmp.wav")), [])


if __name__ == "__main__":
    unittest.main()
