import json
import logging
import threading
import uuid

from sqlalchemy import func
from sqlmodel import Session, select

from app.database import engine
from app.models.local_video_merge import LocalVideoMergeTask
from app.services.rendering import local_video_merge_service
from app.shared.time import elapsed_seconds, utc_now_iso


logger = logging.getLogger(__name__)
_worker_thread: threading.Thread | None = None
_worker_lock = threading.Lock()
_wake_event = threading.Event()


def enqueue(
    session: Session,
    *,
    media_dir: str,
    output_dir: str,
    output_filename: str,
    target_duration: float,
) -> LocalVideoMergeTask:
    local_video_merge_service.validate_local_video_input(
        media_dir, output_dir, output_filename, target_duration
    )
    last_sequence = session.exec(
        select(func.max(LocalVideoMergeTask.queue_sequence))
    ).one()
    task = LocalVideoMergeTask(
        id=uuid.uuid4().hex,
        media_dir=media_dir.strip(),
        output_dir=output_dir.strip(),
        output_filename=local_video_merge_service._normalize_output_filename(output_filename),
        target_duration=target_duration,
        queue_sequence=int(last_sequence or 0) + 1,
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def list_tasks(session: Session, limit: int = 100) -> list[dict]:
    tasks = list(
        session.exec(
            select(LocalVideoMergeTask)
            .order_by(LocalVideoMergeTask.queue_sequence.desc())
            .limit(limit)
        ).all()
    )
    return [serialize_task(session, task) for task in tasks]


def serialize_task(session: Session, task: LocalVideoMergeTask) -> dict:
    queue_position = None
    if task.status == "queued":
        ahead = session.exec(
            select(func.count(LocalVideoMergeTask.id)).where(
                LocalVideoMergeTask.status == "queued",
                LocalVideoMergeTask.queue_sequence < task.queue_sequence,
            )
        ).one()
        running = session.exec(
            select(func.count(LocalVideoMergeTask.id)).where(
                LocalVideoMergeTask.status == "running"
            )
        ).one()
        queue_position = int(ahead or 0) + int(running or 0) + 1
    try:
        result = json.loads(task.result_json or "{}")
    except (TypeError, json.JSONDecodeError):
        result = {}
    data = task.model_dump(exclude={"result_json"})
    data["result"] = result if isinstance(result, dict) and result else None
    data["queue_position"] = queue_position
    data["duration_seconds"] = elapsed_seconds(task.started_at, task.finished_at)
    return data


def recover_interrupted_tasks(session: Session) -> int:
    tasks = list(
        session.exec(
            select(LocalVideoMergeTask).where(LocalVideoMergeTask.status == "running")
        ).all()
    )
    now = utc_now_iso()
    for task in tasks:
        task.status = "queued"
        task.error_message = "后端重启，任务已自动重新排队"
        task.started_at = None
        task.updated_at = now
        session.add(task)
    if tasks:
        session.commit()
    return len(tasks)


def process_next_task() -> bool:
    with Session(engine) as session:
        task = session.exec(
            select(LocalVideoMergeTask)
            .where(LocalVideoMergeTask.status == "queued")
            .order_by(LocalVideoMergeTask.queue_sequence, LocalVideoMergeTask.created_at)
        ).first()
        if not task:
            return False
        now = utc_now_iso()
        task.status = "running"
        task.attempt_count += 1
        task.started_at = now
        task.updated_at = now
        task.error_message = None
        session.add(task)
        session.commit()
        task_id = task.id
        try:
            result = local_video_merge_service.compose_local_video(
                task.media_dir,
                task.output_dir,
                task.output_filename,
                task.target_duration,
            )
        except Exception as exc:
            logger.exception("Local video merge task %s failed", task_id)
            session.rollback()
            current = session.get(LocalVideoMergeTask, task_id)
            if current:
                finished = utc_now_iso()
                current.status = "failed"
                current.error_message = str(exc)[-4000:]
                current.finished_at = finished
                current.updated_at = finished
                session.add(current)
                session.commit()
        else:
            current = session.get(LocalVideoMergeTask, task_id)
            if current:
                finished = utc_now_iso()
                current.status = "completed"
                current.result_json = json.dumps(result, ensure_ascii=False)
                current.finished_at = finished
                current.updated_at = finished
                session.add(current)
                session.commit()
        return True


def wake_worker() -> None:
    global _worker_thread
    with _worker_lock:
        if not _worker_thread or not _worker_thread.is_alive():
            _worker_thread = threading.Thread(
                target=_worker_loop,
                name="local-video-merge-worker",
                daemon=True,
            )
            _worker_thread.start()
    _wake_event.set()


def recover_and_start_worker() -> None:
    with Session(engine) as session:
        recover_interrupted_tasks(session)
    wake_worker()


def _worker_loop() -> None:
    while True:
        _wake_event.wait(timeout=2)
        _wake_event.clear()
        try:
            while process_next_task():
                pass
        except Exception:
            logger.exception("Local video merge queue failed; it will retry")
