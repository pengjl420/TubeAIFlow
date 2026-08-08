import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

from app.models.narration import VoiceProfile
from app.models.voice_generation import VoiceGenerationTask
from app.services.narration import voice_generation_queue


class VoiceGenerationQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{Path(self.temp_dir.name) / 'voice-tasks.db'}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(self.engine)
        self.engine_patch = patch.object(voice_generation_queue, "engine", self.engine)
        self.engine_patch.start()
        self.reference_audio = Path(self.temp_dir.name) / "reference.wav"
        self.reference_audio.write_bytes(b"audio")

    def tearDown(self) -> None:
        self.engine_patch.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_enqueue_keeps_whole_text_and_normalizes_wav_filename(self) -> None:
        with Session(self.engine) as session:
            session.add(VoiceProfile(
                id="voice", name="Narrator", reference_audio_path=str(self.reference_audio)
            ))
            session.commit()
            task = voice_generation_queue.enqueue(
                session,
                voice_profile_id="voice",
                text="第一句。\n第二句。",
                output_filename="完整配音",
            )

            self.assertEqual(task.text, "第一句。\n第二句。")
            self.assertEqual(task.output_filename, "完整配音.wav")
            self.assertEqual(task.status, "queued")
            self.assertEqual(voice_generation_queue.serialize_task(session, task)["queue_position"], 1)

    def test_worker_processes_fifo_and_persists_audio_result(self) -> None:
        with Session(self.engine) as session:
            session.add(VoiceProfile(
                id="voice", name="Narrator", reference_audio_path=str(self.reference_audio)
            ))
            session.add(VoiceGenerationTask(
                id="first", voice_profile_id="voice", voice_profile_name="Narrator",
                text="first", output_filename="first.wav", queue_sequence=1,
            ))
            session.add(VoiceGenerationTask(
                id="second", voice_profile_id="voice", voice_profile_name="Narrator",
                text="second", output_filename="second.wav", queue_sequence=2,
            ))
            session.commit()

        calls: list[str] = []

        def fake_generate(task_id, _profile, _text, filename):
            calls.append(task_id)
            return {"output_path": str(Path(self.temp_dir.name) / filename), "duration": 2.5}

        with patch.object(voice_generation_queue.tts_service, "generate_single_audio", side_effect=fake_generate):
            self.assertTrue(voice_generation_queue.process_next_task())
            self.assertTrue(voice_generation_queue.process_next_task())
            self.assertFalse(voice_generation_queue.process_next_task())

        self.assertEqual(calls, ["first", "second"])
        with Session(self.engine) as session:
            self.assertEqual(session.get(VoiceGenerationTask, "first").status, "completed")
            self.assertEqual(session.get(VoiceGenerationTask, "second").duration, 2.5)

    def test_rejects_text_longer_than_fifty_thousand_characters(self) -> None:
        with Session(self.engine) as session:
            session.add(VoiceProfile(
                id="voice", name="Narrator", reference_audio_path=str(self.reference_audio)
            ))
            session.commit()

            with self.assertRaisesRegex(ValueError, "50000"):
                voice_generation_queue.enqueue(
                    session,
                    voice_profile_id="voice",
                    text="字" * 50001,
                    output_filename="too-long.wav",
                )


if __name__ == "__main__":
    unittest.main()
