import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.api import tasks
from app.database import get_session
from app.models.project import Project
from app.models.storyboard import VisualScene
from app.models.task import TaskRun


class SceneJobApiTests(unittest.TestCase):
    def test_scene_storyboard_regeneration_is_queued_as_api_job(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(
                f"sqlite:///{Path(directory) / 'storyboard-job.db'}",
                connect_args={"check_same_thread": False},
            )
            SQLModel.metadata.create_all(engine)
            with Session(engine) as session:
                session.add(Project(id="p1", name="Project", status="review_required"))
                session.add(
                    VisualScene(
                        id="s1",
                        project_id="p1",
                        scene_index=1,
                        start_ms=0,
                        end_ms=5000,
                        narration="Narration",
                    )
                )
                session.commit()

            app = FastAPI()
            app.include_router(tasks.router, prefix="/api")

            def test_session():
                with Session(engine) as session:
                    yield session

            app.dependency_overrides[get_session] = test_session
            with patch.object(tasks.task_worker, "wake_worker"):
                with TestClient(app) as client:
                    created = client.post("/api/projects/p1/jobs/scenes/s1/storyboard")

            self.assertEqual(created.status_code, 200, created.text)
            self.assertEqual(created.json()["data"]["job_type"], "scene_storyboard_regeneration")
            self.assertEqual(created.json()["data"]["resource_class"], "api")
            self.assertEqual(created.json()["data"]["scene_id"], "s1")
            engine.dispose()

    def test_scene_image_job_uses_persistent_unified_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(
                f"sqlite:///{Path(directory) / 'jobs.db'}",
                connect_args={"check_same_thread": False},
            )
            SQLModel.metadata.create_all(engine)
            with Session(engine) as session:
                session.add(Project(id="p1", name="Project", status="review_required"))
                session.add(
                    VisualScene(
                        id="s1",
                        project_id="p1",
                        scene_index=1,
                        start_ms=0,
                        end_ms=5000,
                        narration="Narration",
                    )
                )
                session.commit()

            app = FastAPI()
            app.include_router(tasks.router, prefix="/api")

            def test_session():
                with Session(engine) as session:
                    yield session

            app.dependency_overrides[get_session] = test_session
            with patch.object(tasks.task_worker, "wake_worker"):
                with TestClient(app) as client:
                    created = client.post("/api/projects/p1/jobs/scenes/s1/images")
                    job_id = created.json()["data"]["id"]
                    paused = client.post(f"/api/projects/p1/jobs/{job_id}/pause")
                    resumed = client.post(f"/api/projects/p1/jobs/{job_id}/resume")
                    fetched = client.get(f"/api/projects/p1/jobs/{job_id}")

            self.assertEqual(created.status_code, 200, created.text)
            self.assertEqual(created.json()["data"]["job_type"], "scene_image_regeneration")
            self.assertEqual(created.json()["data"]["resource_class"], "gpu")
            self.assertEqual(created.json()["data"]["scene_id"], "s1")
            self.assertEqual(paused.json()["data"]["status"], "paused")
            self.assertEqual(resumed.json()["data"]["status"], "queued")
            self.assertEqual(fetched.json()["data"]["id"], job_id)
            with Session(engine) as session:
                self.assertEqual(session.get(Project, "p1").status, "review_required")
                self.assertEqual(session.get(TaskRun, job_id).max_retries, 2)
            engine.dispose()

    def test_maintenance_operations_are_persistent_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(
                f"sqlite:///{Path(directory) / 'maintenance-jobs.db'}",
                connect_args={"check_same_thread": False},
            )
            SQLModel.metadata.create_all(engine)
            with Session(engine) as session:
                session.add(Project(id="p1", name="Project", status="review_required"))
                session.commit()

            app = FastAPI()
            app.include_router(tasks.router, prefix="/api")

            def test_session():
                with Session(engine) as session:
                    yield session

            app.dependency_overrides[get_session] = test_session
            expected = (
                ("assets/scan", "asset_library_scan", "cpu"),
                ("quality-check", "quality_check", "ffmpeg"),
            )
            with patch.object(tasks.task_worker, "wake_worker"):
                with TestClient(app) as client:
                    for endpoint, job_type, resource_class in expected:
                        created = client.post(f"/api/projects/p1/jobs/{endpoint}")
                        self.assertEqual(created.status_code, 200, created.text)
                        data = created.json()["data"]
                        self.assertEqual(data["job_type"], job_type)
                        self.assertEqual(data["resource_class"], resource_class)
                        cancelled = client.post(f"/api/projects/p1/jobs/{data['id']}/cancel")
                        self.assertEqual(cancelled.json()["data"]["status"], "cancelled")
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
