import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.local_video_merge import LocalVideoMergeTask
from app.services.rendering import local_video_merge_queue


class LocalVideoMergeQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.engine_patch = patch.object(local_video_merge_queue, "engine", self.engine)
        self.engine_patch.start()

    def tearDown(self) -> None:
        self.engine_patch.stop()
        self.engine.dispose()

    def test_multiple_tasks_run_one_by_one_in_queue_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Session(self.engine) as session:
                local_video_merge_queue.enqueue(
                    session,
                    media_dir=directory,
                    output_dir=directory,
                    output_filename="first.mp4",
                    target_duration=10,
                )
                second = local_video_merge_queue.enqueue(
                    session,
                    media_dir=directory,
                    output_dir=directory,
                    output_filename="second.mp4",
                    target_duration=20,
                )
                second_data = local_video_merge_queue.serialize_task(session, second)
                self.assertEqual(second_data["queue_position"], 2)

            calls: list[str] = []

            def compose(_media: str, output: str, filename: str, duration: float) -> dict:
                calls.append(filename)
                return {
                    "output_path": str(Path(output) / filename),
                    "requested_duration": duration,
                }

            with patch.object(
                local_video_merge_queue.local_video_merge_service,
                "compose_local_video",
                side_effect=compose,
            ):
                self.assertTrue(local_video_merge_queue.process_next_task())
                self.assertTrue(local_video_merge_queue.process_next_task())
                self.assertFalse(local_video_merge_queue.process_next_task())

            self.assertEqual(calls, ["first.mp4", "second.mp4"])
            with Session(self.engine) as session:
                stored = list(
                    session.exec(
                        select(LocalVideoMergeTask).order_by(LocalVideoMergeTask.queue_sequence)
                    ).all()
                )
                self.assertEqual([task.status for task in stored], ["completed", "completed"])
                self.assertEqual(stored[0].attempt_count, 1)
                self.assertIn("first.mp4", stored[0].result_json)
                self.assertLess(stored[0].queue_sequence, stored[1].queue_sequence)

    def test_failure_does_not_block_the_next_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Session(self.engine) as session:
                for filename in ("failed.mp4", "completed.mp4"):
                    local_video_merge_queue.enqueue(
                        session,
                        media_dir=directory,
                        output_dir=directory,
                        output_filename=filename,
                        target_duration=10,
                    )

            with patch.object(
                local_video_merge_queue.local_video_merge_service,
                "compose_local_video",
                side_effect=[RuntimeError("ffmpeg failed"), {"output_path": "completed.mp4"}],
            ):
                local_video_merge_queue.process_next_task()
                local_video_merge_queue.process_next_task()

            with Session(self.engine) as session:
                stored = list(
                    session.exec(
                        select(LocalVideoMergeTask).order_by(LocalVideoMergeTask.queue_sequence)
                    ).all()
                )
                self.assertEqual([task.status for task in stored], ["failed", "completed"])
                self.assertEqual(stored[0].error_message, "ffmpeg failed")

    def test_running_task_is_requeued_after_restart(self) -> None:
        with Session(self.engine) as session:
            session.add(
                LocalVideoMergeTask(
                    id="interrupted",
                    media_dir="media",
                    output_dir="output",
                    output_filename="out.mp4",
                    target_duration=10,
                    status="running",
                    queue_sequence=1,
                )
            )
            session.commit()
            self.assertEqual(local_video_merge_queue.recover_interrupted_tasks(session), 1)
            recovered = session.get(LocalVideoMergeTask, "interrupted")
            self.assertEqual(recovered.status, "queued")
            self.assertIn("自动重新排队", recovered.error_message)


if __name__ == "__main__":
    unittest.main()
