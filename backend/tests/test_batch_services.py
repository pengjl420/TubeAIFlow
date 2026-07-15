import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.api import batches
from app.database import get_session
from app.models.batch_item import BatchItem
from app.models.batch_job import BatchJob
from app.models.project import Project
from app.services import batch_service, batch_worker, generation_service


class BatchFileTests(unittest.TestCase):
    def test_decode_script_supports_utf8_bom_and_gb18030(self) -> None:
        self.assertEqual(batch_service.decode_script_file("a.txt", b"\xef\xbb\xbfhello"), "hello")
        chinese = "中文逐字稿"
        self.assertEqual(
            batch_service.decode_script_file("b.txt", chinese.encode("gb18030")),
            chinese,
        )

    def test_decode_script_rejects_binary_and_unsupported_files(self) -> None:
        with self.assertRaisesRegex(ValueError, "不是文本"):
            batch_service.decode_script_file("a.txt", b"abc\x00def")
        with self.assertRaisesRegex(ValueError, "不支持"):
            batch_service.decode_script_file("a.docx", b"content")


class GenerationCheckpointTests(unittest.TestCase):
    def test_generation_resumes_from_audio_merge_checkpoint(self) -> None:
        session = MagicMock()
        project = Project(id="p1", name="Project")
        stages: list[str] = []

        with (
            patch.object(generation_service.project_service, "create_segments") as create_segments,
            patch.object(generation_service.tts_service, "generate_project_tts") as generate_tts,
            patch.object(generation_service.audio_service, "merge_project_audio") as merge_audio,
            patch.object(generation_service, "_create_subtitles") as create_subtitles,
            patch.object(generation_service.video_service, "compose_video") as compose_video,
        ):
            generation_service.run_project_generation(
                session,
                project,
                "audio_merge",
                False,
                stages.append,
            )

        create_segments.assert_not_called()
        generate_tts.assert_not_called()
        merge_audio.assert_called_once_with(session, project)
        create_subtitles.assert_called_once_with(session, project)
        compose_video.assert_not_called()
        self.assertEqual(stages, ["subtitles", "completed"])


class BatchApiTests(unittest.TestCase):
    def test_create_batch_preserves_file_order_and_avoids_duplicate_output_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine = create_engine(
                f"sqlite:///{root / 'api.db'}",
                connect_args={"check_same_thread": False},
            )
            SQLModel.metadata.create_all(engine)
            app = FastAPI()
            app.include_router(batches.router, prefix="/api")

            def test_session():
                with Session(engine) as session:
                    yield session

            app.dependency_overrides[get_session] = test_session
            with TestClient(app) as client:
                response = client.post(
                    "/api/batches",
                    data={
                        "name": "Test batch",
                        "output_dir": str(root / "output"),
                        "include_video": "false",
                        "continue_on_error": "true",
                        "auto_start": "false",
                    },
                    files=[
                        ("scripts", ("same.txt", "第一份".encode("utf-8"), "text/plain")),
                        ("scripts", ("same.txt", "第二份".encode("utf-8"), "text/plain")),
                        ("reference_audio", ("voice.wav", b"fake-wave", "audio/wav")),
                    ],
                )

            self.assertEqual(response.status_code, 200, response.text)
            payload = response.json()["data"]
            self.assertEqual(payload["status"], "draft")
            self.assertEqual([item["order_index"] for item in payload["items"]], [1, 2])
            self.assertEqual([item["project_name"] for item in payload["items"]], ["same", "same-2"])
            engine.dispose()


class BatchWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "test.db"
        self.engine = create_engine(
            f"sqlite:///{database_path}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(self.engine)
        self.engine_patch = patch.object(batch_worker, "engine", self.engine)
        self.engine_patch.start()

    def tearDown(self) -> None:
        self.engine_patch.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_worker_processes_items_in_order_and_continues_after_failure(self) -> None:
        with Session(self.engine) as session:
            session.add(
                BatchJob(
                    id="batch",
                    name="Batch",
                    status="queued",
                    total=2,
                    config_json=json.dumps({"include_video": False, "continue_on_error": True}),
                )
            )
            session.add(Project(id="p1", name="One", status="script_imported"))
            session.add(Project(id="p2", name="Two", status="script_imported"))
            # Insert in reverse to prove that order_index drives execution.
            session.add(BatchItem(id="i2", batch_id="batch", project_id="p2", order_index=2, original_filename="2.txt", current_stage="segmenting"))
            session.add(BatchItem(id="i1", batch_id="batch", project_id="p1", order_index=1, original_filename="1.txt", current_stage="segmenting"))
            session.commit()

        calls: list[str] = []

        def fake_generation(_session, project, _stage, _include_video, update_stage):
            calls.append(project.id)
            update_stage("tts")
            if project.id == "p1":
                raise RuntimeError("first failed")
            update_stage("completed")

        with patch.object(
            batch_worker.generation_service,
            "run_project_generation",
            side_effect=fake_generation,
        ):
            self.assertTrue(batch_worker.process_next_item())
            self.assertTrue(batch_worker.process_next_item())

        with Session(self.engine) as session:
            batch = session.get(BatchJob, "batch")
            first = session.get(BatchItem, "i1")
            second = session.get(BatchItem, "i2")
            self.assertIsNotNone(batch)
            self.assertEqual(calls, ["p1", "p2"])
            self.assertEqual(first.status, "failed")
            self.assertIn("first failed", first.error_message or "")
            self.assertEqual(second.status, "completed")
            self.assertEqual(batch.status, "completed_with_errors")
            self.assertEqual(batch.completed, 1)
            self.assertEqual(batch.failed, 1)

    def test_worker_pauses_after_failure_when_configured(self) -> None:
        with Session(self.engine) as session:
            session.add(
                BatchJob(
                    id="batch",
                    name="Batch",
                    status="queued",
                    total=2,
                    config_json=json.dumps({"include_video": False, "continue_on_error": False}),
                )
            )
            session.add(Project(id="p1", name="One"))
            session.add(Project(id="p2", name="Two"))
            session.add(BatchItem(id="i1", batch_id="batch", project_id="p1", order_index=1, original_filename="1.txt", current_stage="segmenting"))
            session.add(BatchItem(id="i2", batch_id="batch", project_id="p2", order_index=2, original_filename="2.txt", current_stage="segmenting"))
            session.commit()

        with patch.object(
            batch_worker.generation_service,
            "run_project_generation",
            side_effect=RuntimeError("stop here"),
        ):
            self.assertTrue(batch_worker.process_next_item())

        with Session(self.engine) as session:
            batch = session.get(BatchJob, "batch")
            second = session.get(BatchItem, "i2")
            self.assertEqual(batch.status, "paused")
            self.assertEqual(second.status, "pending")

    def test_recovery_requeues_interrupted_work_without_losing_stage(self) -> None:
        with Session(self.engine) as session:
            session.add(BatchJob(id="batch", name="Batch", status="running", total=1))
            session.add(Project(id="p1", name="One"))
            session.add(
                BatchItem(
                    id="i1",
                    batch_id="batch",
                    project_id="p1",
                    order_index=1,
                    original_filename="1.txt",
                    status="running",
                    current_stage="subtitles",
                )
            )
            session.commit()

        with patch.object(batch_worker, "start_worker") as start_worker:
            batch_worker.recover_and_start_worker()

        with Session(self.engine) as session:
            batch = session.get(BatchJob, "batch")
            item = session.get(BatchItem, "i1")
            self.assertEqual(batch.status, "queued")
            self.assertEqual(item.status, "pending")
            self.assertEqual(item.current_stage, "subtitles")
            self.assertIn("后端重启", item.error_message or "")
        start_worker.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
