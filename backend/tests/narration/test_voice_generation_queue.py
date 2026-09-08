import tempfile
import unittest
import uuid
import logging
import io
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

from app.models.narration import VoiceProfile
from app.models.voice_generation import VoiceGenerationTask
from app.services.narration import tts_service, voice_generation_queue
from app.infrastructure.logging_config import (
    TaskLogFormatter, current_task_id, task_log_context,
)


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

    def test_enqueue_keeps_transcript_and_exposes_newline_segments(self) -> None:
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
            serialized = voice_generation_queue.serialize_task(session, task)
            self.assertEqual(serialized["queue_position"], 1)
            self.assertEqual(serialized["segment_count"], 2)
            self.assertEqual(
                [item["filename"] for item in serialized["segments"]],
                ["完整配音_0001.wav", "完整配音_0002.wav"],
            )

    def test_split_transcript_uses_only_line_breaks_and_ignores_blank_lines(self) -> None:
        self.assertEqual(
            voice_generation_queue.split_transcript_lines("第一句。第二句！\n\n  第三行  \r\n"),
            ["第一句。第二句！", "第三行"],
        )

    def test_uuid_is_unique_and_persisted_through_resume_and_restart(self) -> None:
        with Session(self.engine) as session:
            session.add(VoiceProfile(
                id="voice", name="Narrator", reference_audio_path=str(self.reference_audio)
            ))
            session.commit()
            tasks = [voice_generation_queue.enqueue(
                session, voice_profile_id="voice", text="same text", output_filename="same.wav",
            ) for _ in range(2)]
            ids = [task.id for task in tasks]
            self.assertNotEqual(*ids)
            self.assertTrue(all(uuid.UUID(identifier).version == 4 for identifier in ids))
            voice_generation_queue.pause_task(session, tasks[0])
            voice_generation_queue.resume_task(session, tasks[0])
            tasks[0].status = "running"
            session.add(tasks[0])
            session.commit()
        with Session(self.engine) as session:
            self.assertEqual(voice_generation_queue.recover_interrupted_tasks(session), 1)
            records = voice_generation_queue.list_tasks(session)
            self.assertEqual({record["id"] for record in records}, set(ids))
            self.assertTrue(all(record["status"] == "queued" for record in records))

    def test_failure_and_success_logs_keep_task_id_without_leaking_to_next_task(self) -> None:
        with Session(self.engine) as session:
            session.add(VoiceProfile(
                id="voice", name="Narrator", reference_audio_path=str(self.reference_audio)
            ))
            for index, task_id in enumerate(["failing", "succeeding"]):
                session.add(VoiceGenerationTask(
                    id=task_id, voice_profile_id="voice", voice_profile_name="Narrator",
                    text="text", output_filename="voice.wav", queue_sequence=index,
                ))
            session.commit()

        def generate(task_id, *_args):
            self.assertEqual(current_task_id(), task_id)
            logging.getLogger("test.provider").info("nested provider log")
            if task_id == "failing":
                raise RuntimeError("synthesis failed")
            return {"output_path": "voice.wav", "duration": 1.0}

        output = io.StringIO()
        handler = logging.StreamHandler(output)
        handler.setFormatter(TaskLogFormatter("%(message)s"))
        root = logging.getLogger()
        previous_level = root.level
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        try:
            with patch.object(tts_service, "generate_segmented_audio", side_effect=generate):
                voice_generation_queue.process_next_task()
                self.assertIsNone(current_task_id())
                voice_generation_queue.process_next_task()
                self.assertIsNone(current_task_id())
        finally:
            root.removeHandler(handler)
            root.setLevel(previous_level)
            handler.close()
        log = output.getvalue()
        self.assertIn("[task_id=failing] nested provider log", log)
        self.assertIn("[task_id=succeeding] nested provider log", log)
        self.assertIn("[task_id=failing] RuntimeError: synthesis failed", log)
        self.assertIn("[task_id=succeeding] Voice generation attempt finished: status=completed", log)
        self.assertTrue(all(line.startswith("[task_id=") for line in log.splitlines()))
        with Session(self.engine) as session:
            self.assertEqual(session.get(VoiceGenerationTask, "failing").status, "failed")
            self.assertEqual(session.get(VoiceGenerationTask, "succeeding").status, "completed")

    def test_runner_logs_tag_and_redact_every_line_before_cancellation(self) -> None:
        logs_dir = Path(self.temp_dir.name)
        result = subprocess.CompletedProcess([], 1, "line one\nline two\n", "password=hidden\nfailed\n")
        with (
            task_log_context("runner-task"),
            patch.object(tts_service, "_run_controlled_process", return_value=result) as run,
            patch.object(tts_service.task_control, "check_cancelled", side_effect=tts_service.task_control.TaskCancelledError("paused")),
        ):
            with self.assertRaises(tts_service.task_control.TaskCancelledError):
                tts_service._execute_batch_runner(
                    "voice-generation-runner-task", ["python"], logs_dir,
                    logs_dir, logs_dir / "result.json", "test-provider",
                )
        self.assertEqual(run.call_args.kwargs["env"]["TUBEAIFOLW_TASK_ID"], "runner-task")
        files = list(logs_dir.glob("*.log"))
        self.assertEqual(len(files), 4)
        for path in files:
            content = path.read_text(encoding="utf-8")
            self.assertNotIn("hidden", content)
            self.assertTrue(all(line.startswith("[task_id=runner-task] ") for line in content.splitlines()))

    def test_pause_and_resume_queued_task(self) -> None:
        with Session(self.engine) as session:
            task = VoiceGenerationTask(
                id="task", voice_profile_id="voice", voice_profile_name="Narrator",
                text="text", output_filename="voice.wav", queue_sequence=1,
            )
            session.add(task)
            session.commit()

            voice_generation_queue.pause_task(session, task)
            self.assertEqual(task.status, "paused")
            self.assertIsNone(voice_generation_queue.serialize_task(session, task)["queue_position"])

            voice_generation_queue.resume_task(session, task)
            self.assertEqual(task.status, "queued")
            self.assertEqual(voice_generation_queue.serialize_task(session, task)["queue_position"], 1)

    def test_delete_non_running_task_removes_record(self) -> None:
        with Session(self.engine) as session:
            task = VoiceGenerationTask(
                id="task", voice_profile_id="voice", voice_profile_name="Narrator",
                text="text", output_filename="voice.wav", queue_sequence=1, status="paused",
            )
            session.add(task)
            session.commit()

            with (
                patch.object(voice_generation_queue, "get_settings", return_value=SimpleNamespace(workspace_dir=Path(self.temp_dir.name))),
                patch.object(voice_generation_queue, "move_existing_to_recycle_bin", return_value=[]) as recycle,
            ):
                self.assertEqual(voice_generation_queue.delete_task(session, task), [])

            self.assertIsNone(session.get(VoiceGenerationTask, "task"))
            recycle.assert_called_once()

    def test_delete_rejects_running_task(self) -> None:
        with Session(self.engine) as session:
            task = VoiceGenerationTask(
                id="task", voice_profile_id="voice", voice_profile_name="Narrator",
                text="text", output_filename="voice.wav", queue_sequence=1, status="running",
            )
            session.add(task)
            session.commit()
            with self.assertRaisesRegex(ValueError, "先暂停"):
                voice_generation_queue.delete_task(session, task)

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

        def fake_generate(task_id, _profile, texts, filename):
            calls.append(task_id)
            self.assertEqual(texts, [task_id])
            return {"output_path": str(Path(self.temp_dir.name) / filename), "duration": 2.5, "segments": []}

        with patch.object(voice_generation_queue.tts_service, "generate_segmented_audio", side_effect=fake_generate):
            self.assertTrue(voice_generation_queue.process_next_task())
            self.assertTrue(voice_generation_queue.process_next_task())
            self.assertFalse(voice_generation_queue.process_next_task())

        self.assertEqual(calls, ["first", "second"])
        with Session(self.engine) as session:
            self.assertEqual(session.get(VoiceGenerationTask, "first").status, "completed")
            self.assertEqual(session.get(VoiceGenerationTask, "second").duration, 2.5)

    def test_pausing_running_task_keeps_paused_status(self) -> None:
        with Session(self.engine) as session:
            session.add(VoiceProfile(
                id="voice", name="Narrator", reference_audio_path=str(self.reference_audio)
            ))
            session.add(VoiceGenerationTask(
                id="task", voice_profile_id="voice", voice_profile_name="Narrator",
                text="text", output_filename="voice.wav", queue_sequence=1,
            ))
            session.commit()

        def fake_generate(*_args):
            with Session(self.engine) as pause_session:
                running = pause_session.get(VoiceGenerationTask, "task")
                self.assertEqual(running.status, "running")
                voice_generation_queue.pause_task(pause_session, running)
            return {"output_path": "ignored.wav", "duration": 1.0, "segments": []}

        with patch.object(voice_generation_queue.tts_service, "generate_segmented_audio", side_effect=fake_generate):
            self.assertTrue(voice_generation_queue.process_next_task())

        with Session(self.engine) as session:
            task = session.get(VoiceGenerationTask, "task")
            self.assertEqual(task.status, "paused")
            self.assertIsNone(task.finished_at)

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

    def test_segmented_generation_names_segments_from_output_and_merges_full_audio(self) -> None:
        profile = VoiceProfile(
            id="voice", name="Narrator", reference_audio_path=str(self.reference_audio)
        )

        def fake_batch(_engine, _project, _reference, segments, audio_dir, _logs_dir):
            for segment in segments:
                (audio_dir / f"{segment.segment_id}.wav").write_bytes(b"wav")

        def fake_ffmpeg(args):
            Path(args[-1]).write_bytes(b"merged")

        with (
            patch.object(tts_service, "get_settings", return_value=SimpleNamespace(workspace_dir=Path(self.temp_dir.name))),
            patch.object(tts_service.voice_profile_service, "load_profile_config", return_value={}),
            patch.object(tts_service.voice_profile_service, "profile_language", return_value="zh-CN"),
            patch.object(tts_service.voice_profile_service, "profile_cosyvoice_speed", return_value=1.0),
            patch.object(tts_service, "_validate_configuration", return_value=("qwen3_tts", self.reference_audio)),
            patch.object(tts_service, "_run_tts_batch", side_effect=fake_batch),
            patch.object(tts_service, "run_ffmpeg", side_effect=fake_ffmpeg),
            patch.object(tts_service, "probe_duration", return_value=1.25),
        ):
            result = tts_service.generate_segmented_audio(
                "task", profile, ["第一行", "第二行"], "人物开场白.wav"
            )

        self.assertEqual(Path(result["output_path"]).name, "人物开场白.wav")
        self.assertEqual(
            [item["filename"] for item in result["segments"]],
            ["人物开场白_0001.wav", "人物开场白_0002.wav"],
        )
        self.assertTrue(Path(result["output_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
