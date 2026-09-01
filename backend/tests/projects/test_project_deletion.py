import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

from app.infrastructure import recycle_bin
from app.models.narration import Segment
from app.models.project import Project
from app.models.task import TaskRun
from app.services.projects import project_service


class RecycleBinTests(unittest.TestCase):
    def test_missing_files_are_ignored_and_nested_paths_are_recycled_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_dir = root / "project"
            nested_file = project_dir / "audio" / "voice.wav"
            nested_file.parent.mkdir(parents=True)
            nested_file.write_bytes(b"audio")
            missing = root / "already-deleted.mp4"

            with patch.object(recycle_bin, "send2trash") as send_to_trash:
                recycled = recycle_bin.move_existing_to_recycle_bin(
                    [missing, nested_file, project_dir]
                )

            self.assertEqual(recycled, [str(project_dir.resolve())])
            send_to_trash.assert_called_once_with(str(project_dir.resolve()))


class ProjectDeletionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.engine = create_engine(
            f"sqlite:///{self.root / 'test.db'}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_delete_removes_database_records_when_files_are_already_missing(self) -> None:
        project = Project(
            id="project-delete",
            name="Delete me",
            status="completed",
            output_dir=str(self.root / "missing-output"),
            config_json='{"output_filename": "delete-me"}',
        )
        segment = Segment(
            id="project-delete_0001",
            project_id=project.id,
            segment_id="0001",
            segment_index=1,
            text="测试",
        )
        with Session(self.engine) as session:
            session.add(project)
            session.add(segment)
            session.commit()

            with patch.object(
                project_service,
                "get_settings",
                return_value=SimpleNamespace(workspace_dir=self.root / "workspace"),
            ):
                result = project_service.delete_project(session, project)

            self.assertEqual(result["recycled_paths"], [])
            self.assertIsNone(session.get(Project, project.id))
            self.assertIsNone(session.get(Segment, segment.id))

    def test_delete_rejects_an_active_task(self) -> None:
        project = Project(id="project-running", name="Running", status="narration_in_progress")
        task = TaskRun(
            id="task-running",
            project_id=project.id,
            status="running",
            queue_sequence=1,
        )
        with Session(self.engine) as session:
            session.add(project)
            session.add(task)
            session.commit()

            with self.assertRaisesRegex(ValueError, "请先强制停止"):
                project_service.delete_project(session, project)

            self.assertIsNotNone(session.get(Project, project.id))

    def test_failed_recycle_persists_retryable_deletion_intent(self) -> None:
        output = self.root / "output"
        output.mkdir()
        artifact = output / "delete-me.mp4"
        artifact.write_bytes(b"video")
        project = Project(
            id="project-retry-delete",
            name="Delete me",
            status="completed",
            output_dir=str(output),
            config_json='{"output_filename":"delete-me"}',
        )
        with Session(self.engine) as session:
            session.add(project)
            session.commit()
            with (
                patch.object(
                    project_service,
                    "get_settings",
                    return_value=SimpleNamespace(workspace_dir=self.root / "workspace"),
                ),
                patch.object(
                    project_service,
                    "move_existing_to_recycle_bin",
                    side_effect=OSError("recycle unavailable"),
                ),
            ):
                with self.assertRaisesRegex(OSError, "recycle unavailable"):
                    project_service.delete_project(session, project)

            persisted = session.get(Project, project.id)
            self.assertEqual(persisted.status, "deleting")
            deletion = json.loads(persisted.config_json)["_deletion"]
            self.assertIn(str(artifact), deletion["artifact_paths"])


if __name__ == "__main__":
    unittest.main()
