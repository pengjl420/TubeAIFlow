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
from app.workflows import render_jobs


class SceneJobApiTests(unittest.TestCase):
    def test_final_render_job_renders_dirty_scenes_before_composition(self) -> None:
        engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(engine)
        transitions: list[str] = []
        try:
            with Session(engine) as session:
                project = Project(id="p1", name="Project")
                session.add(project)
                session.add(
                    TaskRun(
                        id="final-job",
                        project_id=project.id,
                        workflow="final_render",
                        job_type="final_render",
                        status="running",
                        current_stage="scene_render",
                        queue_sequence=1,
                    )
                )
                session.commit()
                with (
                    patch.object(render_jobs.scene_renderer, "render_all_scenes") as render_scenes,
                    patch.object(render_jobs.visual_track_composer, "compose_visual_track") as visual,
                    patch.object(
                        render_jobs.final_renderer,
                        "compose_final_video",
                        return_value={"path": "final.mp4"},
                    ) as final,
                ):
                    render_jobs.run_final_render_job(
                        session, project, "scene_render", True, transitions.append
                    )

                render_scenes.assert_called_once_with(session, project)
                visual.assert_called_once_with(session, project)
                final.assert_called_once_with(session, project)
                self.assertEqual(transitions, ["visual_track", "final_render", "completed"])
        finally:
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

    def test_range_preview_and_final_render_jobs_persist_requests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(
                f"sqlite:///{Path(directory) / 'render-jobs.db'}",
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
            with patch.object(tasks.task_worker, "wake_worker"):
                with TestClient(app) as client:
                    preview = client.post(
                        "/api/projects/p1/jobs/preview",
                        json={"start_ms": 15_000, "duration_ms": 60_000},
                    )
                    preview_id = preview.json()["data"]["id"]
                    client.post(f"/api/projects/p1/jobs/{preview_id}/cancel")
                    final = client.post("/api/projects/p1/jobs/final-render")

            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertEqual(preview.json()["data"]["job_type"], "timeline_preview_render")
            self.assertEqual(
                preview.json()["data"]["request"],
                {"start_ms": 15_000, "duration_ms": 60_000},
            )
            self.assertEqual(final.status_code, 200, final.text)
            self.assertEqual(final.json()["data"]["job_type"], "final_render")
            with Session(engine) as session:
                self.assertEqual(session.get(Project, "p1").status, "video_in_progress")
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
