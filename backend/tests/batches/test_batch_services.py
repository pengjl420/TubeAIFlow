import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app.api import batches
from app.database import get_session
from app.models.batch import BatchItem, BatchJob
from app.models.project import Project
from app.models.narration import Segment
from app.models.task import TaskRun
from app.services.batches import batch_service
from app.services.tasks import task_service, task_worker
from app.workflows import narration_generation


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

    def test_batch_detail_includes_per_project_audio_and_run_timing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(f"sqlite:///{Path(directory) / 'batch-metrics.db'}")
            SQLModel.metadata.create_all(engine)
            with Session(engine) as session:
                batch = BatchJob(
                    id="batch", name="Batch", total=1, status="completed",
                    started_at="2026-07-17T03:00:00+00:00",
                    finished_at="2026-07-17T03:03:00+00:00",
                )
                session.add(batch)
                session.add(Project(id="project", name="Project"))
                session.add(BatchItem(
                    id="item", batch_id="batch", project_id="project", order_index=1,
                    original_filename="script.txt", status="completed",
                ))
                session.add(Segment(
                    id="segment", segment_id="0001", project_id="project",
                    segment_index=1, text="文案", duration=12.5,
                ))
                session.add(TaskRun(
                    id="task", project_id="project", batch_id="batch", batch_item_id="item",
                    queue_sequence=1, status="completed",
                    started_at="2026-07-17T03:01:00+00:00",
                    finished_at="2026-07-17T03:02:30+00:00",
                ))
                session.commit()

                response = batch_service.serialize_batch(session, batch)

            self.assertEqual(response["workflow_duration_seconds"], 180.0)
            self.assertEqual(response["items"][0]["audio_duration_seconds"], 12.5)
            self.assertEqual(response["items"][0]["workflow_duration_seconds"], 90.0)
            self.assertEqual(
                response["items"][0]["workflow_started_at"],
                "2026-07-17T03:01:00+00:00",
            )
            engine.dispose()


class GenerationCheckpointTests(unittest.TestCase):
    def test_generation_resumes_from_audio_merge_checkpoint(self) -> None:
        session = MagicMock()
        project = Project(id="p1", name="Project")
        stages: list[str] = []

        with (
            patch.object(narration_generation.project_service, "create_segments") as create_segments,
            patch.object(narration_generation.tts_service, "generate_project_tts") as generate_tts,
            patch.object(narration_generation.audio_service, "merge_project_audio") as merge_audio,
            patch.object(narration_generation.timeline_service, "build_timeline") as build_timeline,
            patch.object(narration_generation.srt_service, "create_full_srt") as create_srt,
            patch.object(narration_generation.rough_cut_service, "compose_video") as compose_video,
        ):
            narration_generation.run_project_generation(
                session,
                project,
                "audio_merge",
                False,
                stages.append,
            )

        create_segments.assert_not_called()
        generate_tts.assert_not_called()
        merge_audio.assert_called_once_with(session, project)
        build_timeline.assert_called_once_with(session, project)
        create_srt.assert_called_once()
        compose_video.assert_not_called()
        self.assertEqual(stages, ["subtitles", "completed"])

    def test_workflow_generates_timeline_and_subtitles_after_audio_merge(self) -> None:
        session = MagicMock()
        project = Project(id="p1", name="Project")
        stages: list[str] = []
        with (
            patch.object(narration_generation.audio_service, "merge_project_audio"),
            patch.object(narration_generation.timeline_service, "build_timeline") as build_timeline,
            patch.object(narration_generation.srt_service, "create_full_srt") as create_srt,
        ):
            narration_generation.run_project_generation(
                session, project, "audio_merge", False, stages.append
            )
        self.assertEqual(project.status, "narration_ready")
        build_timeline.assert_called_once_with(session, project)
        create_srt.assert_called_once()
        self.assertEqual(stages, ["subtitles", "completed"])

    def test_landscape_mode_branches_after_shared_subtitle_stage(self) -> None:
        session = MagicMock()
        project = Project(
            id="p1",
            name="Project",
            config_json='{"include_video":true,"video_mode":"landscape"}',
        )
        stages: list[str] = []
        with (
            patch.object(narration_generation.timeline_service, "build_timeline"),
            patch.object(narration_generation.srt_service, "create_full_srt"),
            patch.object(narration_generation.rough_cut_service, "compose_video") as compose_video,
            patch.object(narration_generation.video_synthesis, "run_video_synthesis") as smart_video,
        ):
            narration_generation.run_project_generation(
                session, project, "subtitles", True, stages.append
            )

        compose_video.assert_called_once_with(session, project)
        smart_video.assert_not_called()
        self.assertEqual(stages, ["video", "completed"])

    def test_landscape_legacy_fcpxml_setting_renders_mp4(self) -> None:
        session = MagicMock()
        project = Project(
            id="p1",
            name="Project",
            config_json='{"include_video":true,"video_mode":"landscape","video_output_format":"fcpxml"}',
        )
        stages: list[str] = []
        with (
            patch.object(narration_generation.rough_cut_service, "compose_video") as compose_video,
        ):
            narration_generation.run_project_generation(
                session, project, "video", True, stages.append
            )

        compose_video.assert_called_once_with(session, project)
        self.assertEqual(stages, ["completed"])

    def test_audio_only_legacy_fcpxml_setting_does_not_export_video_or_project(self) -> None:
        session = MagicMock()
        project = Project(
            id="p1",
            name="Project",
            config_json='{"video_mode":"none","video_output_format":"fcpxml"}',
        )
        stages: list[str] = []

        with (
            patch.object(narration_generation.timeline_service, "build_timeline"),
            patch.object(narration_generation.srt_service, "create_full_srt"),
            patch.object(
                narration_generation.video_synthesis, "run_video_synthesis"
            ) as video_workflow,
        ):
            narration_generation.run_project_generation(
                session, project, "subtitles", False, stages.append
            )

        video_workflow.assert_not_called()
        self.assertEqual(stages, ["completed"])

    def test_generated_image_mode_branches_after_shared_subtitle_stage(self) -> None:
        session = MagicMock()
        project = Project(
            id="p1",
            name="Project",
            config_json='{"include_video":true,"video_mode":"ai_generated_images"}',
        )
        stages: list[str] = []

        def finish_smart_video(_session, _project, stage, on_stage_changed):
            self.assertEqual(stage, "storyboard")
            on_stage_changed("completed")

        with (
            patch.object(narration_generation.timeline_service, "build_timeline"),
            patch.object(narration_generation.srt_service, "create_full_srt"),
            patch.object(narration_generation.rough_cut_service, "compose_video") as compose_video,
            patch.object(
                narration_generation.video_synthesis,
                "run_video_synthesis",
                side_effect=finish_smart_video,
            ) as smart_video,
        ):
            narration_generation.run_project_generation(
                session, project, "subtitles", True, stages.append
            )

        compose_video.assert_not_called()
        smart_video.assert_called_once()
        self.assertEqual(stages, ["storyboard", "completed"])


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
            with Session(engine) as session:
                tasks = list(session.exec(select(TaskRun).order_by(TaskRun.queue_sequence)).all())
                projects = list(session.exec(select(Project).order_by(Project.created_at)).all())
                self.assertEqual(len(tasks), 2)
                self.assertEqual([project.id for project in projects], [item["project_id"] for item in payload["items"]])
                self.assertEqual([task.status for task in tasks], ["paused", "paused"])
                self.assertEqual(
                    [task.batch_item_id for task in tasks],
                    [item["id"] for item in payload["items"]],
                )
            engine.dispose()

    def test_delete_batch_preserves_projects_and_detaches_task_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(
                f"sqlite:///{Path(directory) / 'delete.db'}",
                connect_args={"check_same_thread": False},
            )
            SQLModel.metadata.create_all(engine)
            with Session(engine) as session:
                session.add(BatchJob(id="batch", name="Batch", status="completed", total=1, completed=1))
                session.add(Project(id="p1", name="One", status="completed"))
                session.add(BatchItem(id="i1", batch_id="batch", project_id="p1", order_index=1, original_filename="1.txt", status="completed"))
                session.add(TaskRun(id="t1", project_id="p1", batch_id="batch", batch_item_id="i1", status="completed", queue_sequence=1))
                session.commit()

                result = batch_service.delete_batch(session, session.get(BatchJob, "batch"))

                self.assertTrue(result["projects_preserved"])
                self.assertIsNone(session.get(BatchJob, "batch"))
                self.assertIsNone(session.get(BatchItem, "i1"))
                self.assertIsNotNone(session.get(Project, "p1"))
                task = session.get(TaskRun, "t1")
                self.assertIsNotNone(task)
                self.assertIsNone(task.batch_id)
                self.assertIsNone(task.batch_item_id)
            engine.dispose()

    def test_delete_batch_rejects_running_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(
                f"sqlite:///{Path(directory) / 'running.db'}",
                connect_args={"check_same_thread": False},
            )
            SQLModel.metadata.create_all(engine)
            with Session(engine) as session:
                batch = BatchJob(id="batch", name="Batch", status="running", total=1)
                session.add(batch)
                session.add(Project(id="p1", name="One", status="narration_in_progress"))
                session.add(BatchItem(id="i1", batch_id="batch", project_id="p1", order_index=1, original_filename="1.txt", status="running"))
                session.add(TaskRun(id="t1", project_id="p1", batch_id="batch", batch_item_id="i1", status="running", queue_sequence=1))
                session.commit()

                with self.assertRaisesRegex(ValueError, "先暂停"):
                    batch_service.delete_batch(session, batch)

                self.assertIsNotNone(session.get(BatchJob, "batch"))
                self.assertIsNotNone(session.get(Project, "p1"))
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
        self.engine_patch = patch.object(task_worker, "engine", self.engine)
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
            session.add(TaskRun(id="t2", project_id="p2", batch_id="batch", batch_item_id="i2", queue_sequence=2))
            session.add(TaskRun(id="t1", project_id="p1", batch_id="batch", batch_item_id="i1", queue_sequence=1))
            session.commit()

        calls: list[str] = []

        def fake_generation(_session, project, _stage, _include_video, update_stage):
            calls.append(project.id)
            update_stage("tts")
            if project.id == "p1":
                raise RuntimeError("first failed")
            update_stage("completed")

        with patch.object(
            task_worker.narration_generation,
            "run_project_generation",
            side_effect=fake_generation,
        ):
            self.assertTrue(task_worker.process_next_task())
            self.assertTrue(task_worker.process_next_task())

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
            session.add(TaskRun(id="t1", project_id="p1", batch_id="batch", batch_item_id="i1", queue_sequence=1))
            session.add(TaskRun(id="t2", project_id="p2", batch_id="batch", batch_item_id="i2", queue_sequence=2))
            session.commit()

        with patch.object(
            task_worker.narration_generation,
            "run_project_generation",
            side_effect=RuntimeError("stop here"),
        ):
            self.assertTrue(task_worker.process_next_task())

        with Session(self.engine) as session:
            batch = session.get(BatchJob, "batch")
            second = session.get(BatchItem, "i2")
            self.assertEqual(batch.status, "paused")
            self.assertEqual(second.status, "pending")
            batch_service.retry_item(session, batch, "i1")
            first_retry = task_service.get_latest_batch_item_task(session, "i1")
            second_task = task_service.get_latest_batch_item_task(session, "i2")
            self.assertEqual(first_retry.status, "queued")
            self.assertEqual(second_task.status, "queued")
            self.assertEqual(session.get(BatchJob, "batch").status, "queued")

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
            session.add(
                TaskRun(
                    id="t1",
                    project_id="p1",
                    batch_id="batch",
                    batch_item_id="i1",
                    status="running",
                    current_stage="subtitles",
                    queue_sequence=1,
                )
            )
            session.commit()

        with Session(self.engine) as session:
            recovered = task_worker.recover_interrupted_tasks(session)

        with Session(self.engine) as session:
            batch = session.get(BatchJob, "batch")
            item = session.get(BatchItem, "i1")
            task = session.get(TaskRun, "t1")
            self.assertEqual(batch.status, "queued")
            self.assertEqual(item.status, "pending")
            self.assertEqual(item.current_stage, "subtitles")
            self.assertEqual(task.status, "queued")
            self.assertEqual(task.compensation_count, 1)
            self.assertIn("自动补偿", item.error_message or "")
        self.assertEqual(recovered, 1)


if __name__ == "__main__":
    unittest.main()
