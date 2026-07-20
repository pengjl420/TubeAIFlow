import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

from app.api import tts
from app.models.narration import Segment
from app.models.project import Project
from app.models.task import TaskRun


class TtsWorkflowResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{Path(self.temp_dir.name) / 'resume.db'}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temp_dir.cleanup()

    def _add_failed_task(self, session: Session) -> None:
        session.add(Project(id="project", name="Project", status="failed"))
        session.add(
            TaskRun(
                id="task",
                project_id="project",
                workflow="narration_generation",
                status="failed",
                current_stage="tts",
                queue_sequence=1,
                error_message="TTS 有 1 段生成失败",
            )
        )

    def test_last_repaired_segment_requeues_workflow_at_audio_merge(self) -> None:
        with Session(self.engine) as session:
            self._add_failed_task(session)
            session.add(
                Segment(
                    id="project_0001",
                    project_id="project",
                    segment_id="0001",
                    segment_index=1,
                    text="完成",
                    status="completed",
                )
            )
            session.commit()

            with patch.object(tts.task_worker, "wake_worker") as wake_worker:
                tts._resume_failed_workflow_after_tts_repair(session, "project")

            task = session.get(TaskRun, "task")
            self.assertEqual(task.status, "queued")
            self.assertEqual(task.current_stage, "audio_merge")
            wake_worker.assert_called_once_with()

    def test_incomplete_segment_keeps_failed_workflow_stopped(self) -> None:
        with Session(self.engine) as session:
            self._add_failed_task(session)
            session.add(
                Segment(
                    id="project_0001",
                    project_id="project",
                    segment_id="0001",
                    segment_index=1,
                    text="失败",
                    status="failed",
                )
            )
            session.commit()

            with patch.object(tts.task_worker, "wake_worker") as wake_worker:
                tts._resume_failed_workflow_after_tts_repair(session, "project")

            task = session.get(TaskRun, "task")
            self.assertEqual(task.status, "failed")
            self.assertEqual(task.current_stage, "tts")
            wake_worker.assert_not_called()


if __name__ == "__main__":
    unittest.main()
