import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine as create_sqlalchemy_engine, inspect
from sqlmodel import Session, SQLModel, create_engine

from app import database
from app.api import tasks
from app.database import get_session
from app.models.batch import BatchItem, BatchJob
from app.models.project import Project
from app.models.task import TaskRun
from app.services.tasks import task_service, task_worker


class TaskQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{Path(self.temp_dir.name) / 'tasks.db'}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(self.engine)
        self.engine_patch = patch.object(task_worker, "engine", self.engine)
        self.engine_patch.start()

    def tearDown(self) -> None:
        self.engine_patch.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_single_and_batch_projects_share_one_fifo_queue(self) -> None:
        with Session(self.engine) as session:
            session.add(BatchJob(id="batch", name="Batch", status="queued", total=1))
            session.add(Project(id="batch-project", name="Batch project"))
            session.add(Project(id="single-project", name="Single project"))
            session.add(
                BatchItem(
                    id="item",
                    batch_id="batch",
                    project_id="batch-project",
                    order_index=1,
                    original_filename="batch.txt",
                )
            )
            session.add(
                TaskRun(
                    id="single-task",
                    project_id="single-project",
                    queue_sequence=1,
                )
            )
            session.add(
                TaskRun(
                    id="batch-task",
                    project_id="batch-project",
                    batch_id="batch",
                    batch_item_id="item",
                    queue_sequence=2,
                )
            )
            session.commit()

        calls: list[str] = []
        running_counts: list[int] = []

        def fake_generation(session, project, _stage, _include_video, update_stage):
            calls.append(project.id)
            running_counts.append(
                len(session.exec(TaskRun.__table__.select().where(TaskRun.status == "running")).all())
            )
            update_stage("completed")

        with patch.object(
            task_worker.narration_generation,
            "run_project_generation",
            side_effect=fake_generation,
        ):
            self.assertTrue(task_worker.process_next_task())
            self.assertTrue(task_worker.process_next_task())
            self.assertFalse(task_worker.process_next_task())

        self.assertEqual(calls, ["single-project", "batch-project"])
        self.assertEqual(running_counts, [1, 1])
        with Session(self.engine) as session:
            self.assertEqual(session.get(TaskRun, "single-task").status, "completed")
            self.assertEqual(session.get(TaskRun, "batch-task").status, "completed")
            self.assertEqual(session.get(BatchJob, "batch").status, "completed")

    def test_enqueue_reuses_active_task_but_allows_a_new_run_after_completion(self) -> None:
        with Session(self.engine) as session:
            project = Project(id="project", name="Project", config_json="{}")
            session.add(project)
            session.commit()
            first = task_service.enqueue_project_task(session, project, include_video=False)
            duplicate = task_service.enqueue_project_task(session, project, include_video=False)
            self.assertEqual(duplicate.id, first.id)
            first.status = "completed"
            session.add(first)
            session.commit()
            second = task_service.enqueue_project_task(session, project, include_video=False)
            self.assertNotEqual(second.id, first.id)
            self.assertGreater(second.queue_sequence, first.queue_sequence)

    def test_restart_compensation_keeps_current_stage_and_checkpoint(self) -> None:
        with Session(self.engine) as session:
            session.add(Project(id="project", name="Project"))
            session.add(
                TaskRun(
                    id="task",
                    project_id="project",
                    status="running",
                    current_stage="audio_merge",
                    queue_sequence=1,
                    checkpoint_json='{"current_stage":"audio_merge","stage_history":[]}',
                )
            )
            session.commit()
            self.assertEqual(task_worker.recover_interrupted_tasks(session), 1)

        with Session(self.engine) as session:
            task = session.get(TaskRun, "task")
            self.assertEqual(task.status, "queued")
            self.assertEqual(task.current_stage, "audio_merge")
            self.assertEqual(task.compensation_count, 1)
            self.assertIn('"event": "recovered"', task.checkpoint_json)

    def test_restart_reconciles_batch_if_shutdown_happened_after_task_commit(self) -> None:
        with Session(self.engine) as session:
            session.add(BatchJob(id="batch", name="Batch", status="running", total=1))
            session.add(Project(id="project", name="Project", status="completed"))
            session.add(
                BatchItem(
                    id="item",
                    batch_id="batch",
                    project_id="project",
                    order_index=1,
                    original_filename="script.txt",
                    status="completed",
                    current_stage="completed",
                )
            )
            session.add(
                TaskRun(
                    id="task",
                    project_id="project",
                    batch_id="batch",
                    batch_item_id="item",
                    status="completed",
                    current_stage="completed",
                    queue_sequence=1,
                )
            )
            session.commit()
            self.assertEqual(task_worker.recover_interrupted_tasks(session), 0)

        with Session(self.engine) as session:
            batch = session.get(BatchJob, "batch")
            self.assertEqual(batch.status, "completed")
            self.assertEqual(batch.completed, 1)


class DatabaseMigrationTests(unittest.TestCase):
    def test_existing_database_adds_task_table_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = create_sqlalchemy_engine(f"sqlite:///{Path(directory) / 'legacy.db'}")
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "CREATE TABLE projects (id VARCHAR PRIMARY KEY, name VARCHAR NOT NULL)"
                )
            with patch.object(database, "engine", engine):
                database._apply_migrations()
                database._apply_migrations()
                table_names = set(inspect(engine).get_table_names())
                columns = {column["name"] for column in inspect(engine).get_columns("task_runs")}
                indexes = {index["name"] for index in inspect(engine).get_indexes("task_runs")}
                with engine.connect() as connection:
                    versions = connection.exec_driver_sql(
                        "SELECT version FROM schema_migrations ORDER BY version"
                    ).fetchall()
            engine.dispose()

        self.assertIn("task_runs", table_names)
        self.assertIn("checkpoint_json", columns)
        self.assertIn("compensation_count", columns)
        self.assertIn("uq_task_runs_active_project", indexes)
        self.assertIn("uq_task_runs_single_running", indexes)
        self.assertIn("subtitle_cues", table_names)
        self.assertIn("visual_scenes", table_names)
        self.assertIn("media_files", table_names)
        self.assertIn("media_shots", table_names)
        self.assertIn("media_keyframes", table_names)
        self.assertIn("scene_candidates", table_names)
        self.assertIn("scene_assignments", table_names)
        self.assertIn("media_provider_states", table_names)
        self.assertIn("media_query_cache", table_names)
        self.assertEqual(versions, [(1,), (2,), (3,), (4,), (5,), (6,), (7,), (8,)])

    def test_source_subtitle_migration_removes_bilingual_schema_and_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = create_sqlalchemy_engine(f"sqlite:///{Path(directory) / 'legacy-subtitles.db'}")
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "CREATE TABLE projects (id VARCHAR PRIMARY KEY, status VARCHAR, config_json VARCHAR)"
                )
                connection.exec_driver_sql(
                    "INSERT INTO projects (id, status, config_json) VALUES "
                    "('p1', 'zh_subtitle_created', "
                    "'{\"include_translation\": false, \"include_video\": true}')"
                )
                connection.exec_driver_sql(
                    """
                    CREATE TABLE segments (
                        id VARCHAR PRIMARY KEY,
                        segment_id VARCHAR NOT NULL,
                        project_id VARCHAR NOT NULL,
                        segment_index INTEGER NOT NULL,
                        text_zh VARCHAR NOT NULL,
                        text_en VARCHAR,
                        audio_path VARCHAR,
                        duration FLOAT,
                        start_time FLOAT,
                        end_time FLOAT,
                        status VARCHAR NOT NULL,
                        error_message VARCHAR,
                        created_at VARCHAR NOT NULL,
                        updated_at VARCHAR NOT NULL
                    )
                    """
                )
                connection.exec_driver_sql(
                    """
                    INSERT INTO segments (
                        id, segment_id, project_id, segment_index, text_zh, text_en,
                        status, created_at, updated_at
                    ) VALUES ('s1', '0001', 'p1', 1, '原文', 'translation', 'pending', 'now', 'now')
                    """
                )
                connection.exec_driver_sql(
                    "CREATE TABLE subtitle_templates "
                    "(id VARCHAR PRIMARY KEY, name VARCHAR, language VARCHAR, config_json VARCHAR)"
                )

            with patch.object(database, "engine", engine):
                database._apply_migrations()
                columns = {column["name"] for column in inspect(engine).get_columns("segments")}
                tables = set(inspect(engine).get_table_names())
                with engine.connect() as connection:
                    segment_text = connection.exec_driver_sql(
                        "SELECT text FROM segments WHERE id = 's1'"
                    ).scalar_one()
                    config_json = connection.exec_driver_sql(
                        "SELECT config_json FROM projects WHERE id = 'p1'"
                    ).scalar_one()
                    project_status = connection.exec_driver_sql(
                        "SELECT status FROM projects WHERE id = 'p1'"
                    ).scalar_one()
            engine.dispose()

        self.assertEqual(segment_text, "原文")
        self.assertEqual(columns, {
            "id", "segment_id", "project_id", "segment_index", "text", "audio_path",
            "duration", "start_time", "end_time", "status", "error_message",
            "created_at", "updated_at",
        })
        self.assertNotIn("subtitle_templates", tables)
        self.assertNotIn("include_translation", config_json)
        self.assertEqual(project_status, "narration_ready")


class TaskApiTests(unittest.TestCase):
    def test_start_endpoint_only_enqueues_and_returns_immediately(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(
                f"sqlite:///{Path(directory) / 'api.db'}",
                connect_args={"check_same_thread": False},
            )
            SQLModel.metadata.create_all(engine)
            with Session(engine) as session:
                session.add(
                    Project(
                        id="project",
                        name="Project",
                        script_clean_path="saved.txt",
                        config_json='{"output_filename":"project","include_video":false}',
                    )
                )
                session.commit()

            app = FastAPI()
            app.include_router(tasks.router, prefix="/api")

            def test_session():
                with Session(engine) as session:
                    yield session

            app.dependency_overrides[get_session] = test_session
            with patch.object(tasks.task_worker, "wake_worker") as wake_worker:
                with TestClient(app) as client:
                    response = client.post("/api/projects/project/workflows/narration/start")

            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["data"]["status"], "queued")
            wake_worker.assert_called_once_with()
            with Session(engine) as session:
                task = task_service.get_latest_project_task(session, "project")
                self.assertEqual(task.status, "queued")
                self.assertEqual(task.attempt_count, 0)
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
