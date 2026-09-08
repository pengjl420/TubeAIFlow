import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError
from sqlmodel import SQLModel, Session, create_engine

from app.config import Settings
from app.models.voice_generation import VoiceGenerationTask
from app.services.settings import cleanup_service as cleanup


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.engine = create_engine(f"sqlite:///{self.root / 'test.db'}")
        SQLModel.metadata.create_all(self.engine)
        self.settings = Settings(workspace_dir=self.root, cleanup_enabled=True,
                                 cleanup_completed_voice_tasks=True)
        self.now = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
        self.old = self.now - timedelta(days=31)

    def tearDown(self):
        self.engine.dispose()
        self.temporary.cleanup()

    def task(self, session, identifier, status="completed", finished=None):
        task = VoiceGenerationTask(id=identifier, voice_profile_id="v",
            voice_profile_name="Voice", text="text", output_filename="a.wav",
            queue_sequence=1, status=status, finished_at=(finished or self.old).isoformat())
        session.add(task)
        session.commit()
        directory = self.root / "voice_generations" / identifier
        (directory / "logs").mkdir(parents=True)
        for name in ["a.wav", "logs/tts.log", "logs/tts_progress.json"]:
            file = directory / name
            file.write_text("data")
            os.utime(file, (self.old.timestamp(), self.old.timestamp()))
        return directory

    def test_only_expired_completed_tasks_are_removed(self):
        with Session(self.engine) as session:
            old = self.task(session, "old")
            keep = [self.task(session, state, state) for state in
                    ["running", "paused", "queued", "failed"]]
            keep.append(self.task(session, "recent", finished=self.now))
            report = cleanup.run_cleanup(session, self.settings, self.now)
            self.assertEqual(report["deleted_tasks"], 1)
            self.assertFalse(old.exists())
            self.assertIsNone(session.get(VoiceGenerationTask, "old"))
            self.assertTrue(all(path.joinpath("a.wav").exists() for path in keep))

    def test_logs_only_preserves_audio_json_and_current_engine_log(self):
        self.settings.cleanup_completed_voice_tasks = False
        logs = self.root / "logs"
        logs.mkdir()
        for name in ["engine.log", "engine.log.1", "backend.stdout.log"]:
            file = logs / name
            file.write_text("log")
            os.utime(file, (self.old.timestamp(), self.old.timestamp()))
        with Session(self.engine) as session:
            directory = self.task(session, "old")
            report = cleanup.run_cleanup(session, self.settings, self.now)
            self.assertEqual(report["deleted_logs"], 2)
            self.assertTrue((directory / "a.wav").exists())
            self.assertTrue((directory / "logs/tts_progress.json").exists())
            self.assertTrue((logs / "engine.log").exists())
            self.assertTrue((logs / "backend.stdout.log").exists())

    def test_live_process_protects_completed_task(self):
        with Session(self.engine) as session:
            directory = self.task(session, "live")
            with patch.object(cleanup.process_runner, "status", return_value={"running": True}):
                cleanup.run_cleanup(session, self.settings, self.now)
            self.assertTrue((directory / "logs/tts.log").exists())

    def test_disabled_and_daily_catchup_persist_across_calls(self):
        with patch.object(cleanup, "get_settings", return_value=self.settings), patch.object(
            cleanup, "engine", self.engine
        ), patch.object(cleanup, "run_cleanup", return_value={"errors": 0}) as run:
            self.settings.cleanup_enabled = False
            cleanup.run_if_due(self.now)
            run.assert_not_called()
            self.settings.cleanup_enabled = True
            cleanup.run_if_due(self.now)
            cleanup.run_if_due(self.now + timedelta(hours=1))
            self.assertEqual(run.call_count, 1)
            # Restart before today's scheduled time catches up the missed day.
            cleanup.run_if_due(self.now + timedelta(days=2, hours=-11))
            self.assertEqual(run.call_count, 2)

    def test_failed_deletion_keeps_database_record_for_retry(self):
        with Session(self.engine) as session:
            self.task(session, "locked")
            with patch.object(cleanup, "remove_tree", side_effect=PermissionError("locked")), \
                    self.assertLogs(cleanup.logger, level="ERROR"):
                report = cleanup.run_cleanup(session, self.settings, self.now)
            self.assertEqual(report["errors"], 1)
            self.assertIsNotNone(session.get(VoiceGenerationTask, "locked"))
            cleanup.run_cleanup(session, self.settings, self.now)
            self.assertIsNone(session.get(VoiceGenerationTask, "locked"))

    def test_path_escape_and_links_are_rejected(self):
        with self.assertRaises(ValueError):
            cleanup.remove_tree(self.root / ".." / "outside", self.root)
        target = self.root / "target"
        target.mkdir()
        link = self.root / "link"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            return  # Windows may deny symlink creation without developer mode.
        with self.assertRaises(ValueError):
            cleanup.remove_tree(link, self.root)
        link.unlink()

    def test_settings_validation_and_expiry_boundary(self):
        for values in [{"cleanup_retention_days": 0}, {"cleanup_daily_time": "24:00"}]:
            with self.assertRaises(ValidationError):
                Settings(**values)
        self.assertFalse(cleanup.expired(self.old.isoformat(), self.old))
        self.assertFalse(cleanup.expired(None, self.old))
        self.assertFalse(cleanup.expired("invalid", self.old))

    def test_status_reflects_saved_settings_and_last_run(self):
        with patch.object(cleanup, "get_settings", return_value=self.settings), patch.object(
            cleanup, "engine", self.engine
        ):
            status = cleanup.get_status(self.now)
            self.assertTrue(status["enabled"])
            self.assertEqual(status["retention_days"], 30)
            self.assertTrue(status["catchup_pending"])
            self.assertIsNone(status["last_run"])
            cleanup.run_if_due(self.now)
            status = cleanup.get_status(self.now)
            self.assertFalse(status["catchup_pending"])
            self.assertEqual(status["last_run"]["errors"], 0)
            self.assertEqual(status["next_run_at"], "2026-09-08T03:00:00+00:00")
            self.settings.cleanup_enabled = False
            self.assertIsNone(cleanup.get_status(self.now)["next_run_at"])

    def test_status_reports_corrupt_history(self):
        directory = self.root / ".runtime"
        directory.mkdir()
        (directory / "cleanup-state.json").write_text("invalid")
        with patch.object(cleanup, "get_settings", return_value=self.settings):
            self.assertIsNotNone(cleanup.get_status(self.now)["error"])


if __name__ == "__main__":
    unittest.main()
