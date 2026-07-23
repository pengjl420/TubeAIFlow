import json
import logging
import os
import threading
import uuid

from sqlmodel import Session, select

from app.database import engine
from app.infrastructure import process_runner as runtime_control
from app.models.batch import BatchItem, BatchJob
from app.models.project import Project
from app.models.task import TaskRun
from app.services.tasks import task_service
from app.shared.time import utc_now_iso
from app.workflows import narration_generation, video_synthesis


logger = logging.getLogger(__name__)
_worker_thread: threading.Thread | None = None
_worker_lock = threading.Lock()
_wake_event = threading.Event()
_worker_id = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"


def _is_video_task(task: TaskRun, stage: str | None = None) -> bool:
    current_stage = stage or task.current_stage
    return (
        task.workflow == "video_synthesis"
        or current_stage == "video"
        or current_stage in video_synthesis.STAGES
    )


def start_worker() -> None:
    global _worker_thread
    with _worker_lock:
        if _worker_thread and _worker_thread.is_alive():
            _wake_event.set()
            return
        _worker_thread = threading.Thread(target=_worker_loop, name="task-worker", daemon=True)
        _worker_thread.start()
    _wake_event.set()


def wake_worker() -> None:
    start_worker()
    _wake_event.set()


def recover_and_start_worker() -> None:
    with Session(engine) as session:
        recover_interrupted_tasks(session)
    start_worker()


def recover_interrupted_tasks(session: Session) -> int:
    now = utc_now_iso()
    recovered = 0
    touched_batch_ids: set[str] = set()
    running_tasks = list(session.exec(select(TaskRun).where(TaskRun.status == "running")).all())
    for task in running_tasks:
        batch = session.get(BatchJob, task.batch_id) if task.batch_id else None
        if batch:
            touched_batch_ids.add(batch.id)
        item = session.get(BatchItem, task.batch_item_id) if task.batch_item_id else None
        if task.cancel_requested and not (batch and batch.status == "paused"):
            task.status = "cancelled"
            task.finished_at = now
            task.error_message = "任务在取消过程中被中断，启动恢复后保持取消状态"
            if item:
                item.status = "failed"
                item.error_message = task.error_message
                item.finished_at = now
        else:
            task.status = "paused" if batch and batch.status == "paused" else "queued"
            task.cancel_requested = False
            task.finished_at = None
            task.compensation_count += 1
            task.last_recovered_at = now
            task.error_message = "任务因后端异常退出中断，已从当前阶段自动补偿并重新排队"
            _append_checkpoint_event(task, "recovered", task.current_stage, now)
            if item:
                item.status = "pending"
                item.current_stage = task.current_stage
                item.error_message = task.error_message
                item.finished_at = None
            recovered += 1
        task.lease_owner = None
        task.heartbeat_at = None
        task.updated_at = now
        session.add(task)
        project = session.get(Project, task.project_id)
        if project:
            project.status = (
                "cancelled"
                if task.status == "cancelled"
                else "video_in_progress"
                if _is_video_task(task)
                else "narration_in_progress"
            )
            project.updated_at = now
            session.add(project)
        if item:
            item.updated_at = now
            session.add(item)

    # Compensate legacy or partially-created batch items that do not yet have a
    # persistent task row. This makes the migration safe for existing queues.
    for item in session.exec(
        select(BatchItem).where(BatchItem.status.in_(["pending", "running"]))
    ).all():
        existing = task_service.get_latest_batch_item_task(session, item.id)
        if existing:
            continue
        project = session.get(Project, item.project_id)
        batch = session.get(BatchJob, item.batch_id)
        if not project or not batch:
            continue
        touched_batch_ids.add(batch.id)
        config = _load_batch_config(batch)
        initial_status = "queued" if batch.status in {"queued", "running"} else "paused"
        task_service.enqueue_project_task(
            session,
            project,
            include_video=bool(config.get("include_video", True)),
            current_stage=item.current_stage or "segmenting",
            batch_id=batch.id,
            batch_item_id=item.id,
            initial_status=initial_status,
            reuse_active=False,
            commit=False,
        )
        if item.status == "running":
            item.status = "pending"
            item.updated_at = now
            session.add(item)
        recovered += 1

    for batch in session.exec(
        select(BatchJob).where(BatchJob.status.in_(["queued", "running"]))
    ).all():
        touched_batch_ids.add(batch.id)
        if batch.status == "running":
            batch.status = "queued"
        batch.updated_at = now
        session.add(batch)
    session.commit()
    for batch_id in touched_batch_ids:
        refresh_batch_status(session, batch_id)
    if recovered:
        logger.warning("Recovered %s interrupted or missing persistent task(s)", recovered)
    return recovered


def process_next_task() -> bool:
    with Session(engine) as session:
        task = session.exec(
            select(TaskRun)
            .where(TaskRun.status == "queued")
            .order_by(TaskRun.queue_sequence, TaskRun.created_at, TaskRun.id)
        ).first()
        if not task:
            return False

        batch = session.get(BatchJob, task.batch_id) if task.batch_id else None
        item = session.get(BatchItem, task.batch_item_id) if task.batch_item_id else None
        if batch and batch.status in {"draft", "paused"}:
            task.status = "paused"
            task.updated_at = utc_now_iso()
            session.add(task)
            session.commit()
            return True

        project = session.get(Project, task.project_id)
        if not project:
            _fail_task(session, task, batch, item, "项目不存在")
            return True

        now = utc_now_iso()
        task.status = "running"
        task.attempt_count += 1
        task.cancel_requested = False
        task.lease_owner = _worker_id
        task.heartbeat_at = now
        task.started_at = task.started_at or now
        task.updated_at = now
        task.error_message = None
        project.status = (
            "video_in_progress"
            if _is_video_task(task)
            else "narration_in_progress"
        )
        project.updated_at = now
        session.add(task)
        session.add(project)
        if item:
            item.status = "running"
            item.current_stage = task.current_stage
            item.started_at = item.started_at or now
            item.updated_at = now
            item.error_message = None
            session.add(item)
        if batch:
            batch.status = "running"
            batch.started_at = batch.started_at or now
            batch.updated_at = now
            session.add(batch)
        session.commit()

        def update_stage(stage: str) -> None:
            current = session.get(TaskRun, task.id)
            if not current:
                raise RuntimeError("Task record disappeared while generation was running")
            changed_at = utc_now_iso()
            completed_stage = current.current_stage
            current.current_stage = stage
            current.heartbeat_at = changed_at
            current.updated_at = changed_at
            _append_checkpoint_event(
                current,
                "stage_completed",
                completed_stage,
                changed_at,
                checkpoint_stage=stage,
                next_stage=stage,
            )
            session.add(current)
            current_item = session.get(BatchItem, current.batch_item_id) if current.batch_item_id else None
            if current_item:
                current_item.current_stage = stage
                current_item.updated_at = changed_at
                session.add(current_item)
            current_project = session.get(Project, current.project_id)
            if current_project:
                current_project.status = (
                    "video_in_progress"
                    if _is_video_task(current, stage)
                    else "narration_in_progress"
                )
                current_project.updated_at = changed_at
                session.add(current_project)
            session.commit()
            session.refresh(current)
            if current.cancel_requested:
                raise runtime_control.TaskCancelledError("Task was stopped by the user")

        try:
            if task.workflow == "narration_generation":
                narration_generation.run_project_generation(
                    session,
                    project,
                    task.current_stage,
                    task.include_video,
                    update_stage,
                )
            elif task.workflow == "video_synthesis":
                video_synthesis.run_video_synthesis(
                    session,
                    project,
                    task.current_stage,
                    update_stage,
                )
            else:
                raise ValueError(f"Unknown workflow: {task.workflow}")
        except runtime_control.TaskCancelledError as exc:
            session.rollback()
            _cancel_task(session, task.id, str(exc))
        except Exception as exc:
            session.rollback()
            logger.exception("Task %s failed at stage %s", task.id, task.current_stage)
            current = session.get(TaskRun, task.id)
            current_batch = session.get(BatchJob, current.batch_id) if current and current.batch_id else None
            current_item = session.get(BatchItem, current.batch_item_id) if current and current.batch_item_id else None
            if current:
                _fail_task(session, current, current_batch, current_item, str(exc))
        else:
            _complete_task(session, task.id)
        return True


def _worker_loop() -> None:
    while True:
        _wake_event.wait(timeout=2)
        _wake_event.clear()
        try:
            while process_next_task():
                pass
        except Exception:
            # A task-level exception is normally persisted by process_next_task.
            # Keep the queue alive if an unexpected worker bookkeeping error occurs.
            logger.exception("Task worker loop failed; it will retry the queue")
            try:
                with Session(engine) as session:
                    recover_interrupted_tasks(session)
            except Exception:
                logger.exception("Task worker compensation pass failed")


def _complete_task(session: Session, task_id: str) -> None:
    task = session.get(TaskRun, task_id)
    if not task:
        return
    now = utc_now_iso()
    task.status = "completed"
    task.current_stage = "completed"
    task.cancel_requested = False
    task.lease_owner = None
    task.heartbeat_at = now
    task.finished_at = now
    task.updated_at = now
    task.error_message = None
    _append_checkpoint_event(task, "completed", "completed", now)
    session.add(task)
    project = session.get(Project, task.project_id)
    if project:
        project.status = (
            "completed"
            if task.workflow == "video_synthesis" or task.include_video
            else "narration_ready"
        )
        project.updated_at = now
        session.add(project)
    item = session.get(BatchItem, task.batch_item_id) if task.batch_item_id else None
    if item:
        item.status = "completed"
        item.current_stage = "completed"
        item.finished_at = now
        item.updated_at = now
        item.error_message = None
        session.add(item)
    batch = session.get(BatchJob, task.batch_id) if task.batch_id else None
    session.commit()
    if batch:
        refresh_batch_status(session, batch.id)


def _fail_task(
    session: Session,
    task: TaskRun,
    batch: BatchJob | None,
    item: BatchItem | None,
    error: str,
) -> None:
    now = utc_now_iso()
    task.status = "failed"
    task.cancel_requested = False
    task.lease_owner = None
    task.heartbeat_at = now
    task.finished_at = now
    task.updated_at = now
    task.error_message = (error or "生成失败")[-4000:]
    _append_checkpoint_event(task, "failed", task.current_stage, now, task.error_message)
    session.add(task)
    project = session.get(Project, task.project_id)
    if project:
        project.status = "failed"
        project.updated_at = now
        session.add(project)
    if item:
        item.status = "failed"
        item.current_stage = task.current_stage
        item.error_message = task.error_message
        item.finished_at = now
        item.updated_at = now
        session.add(item)
    if batch:
        config = _load_batch_config(batch)
        if not bool(config.get("continue_on_error", True)):
            batch.status = "paused"
            batch.updated_at = now
            session.add(batch)
            for pending_task in task_service.list_batch_tasks(session, batch.id):
                task_service.pause_queued_task(session, pending_task)
    session.commit()
    if batch:
        refresh_batch_status(session, batch.id)


def _cancel_task(session: Session, task_id: str, error: str) -> None:
    task = session.get(TaskRun, task_id)
    if not task:
        return
    now = utc_now_iso()
    batch = session.get(BatchJob, task.batch_id) if task.batch_id else None
    item = session.get(BatchItem, task.batch_item_id) if task.batch_item_id else None
    paused_by_batch = bool(batch and batch.status == "paused")
    task.status = "paused" if paused_by_batch else "cancelled"
    task.cancel_requested = False
    task.lease_owner = None
    task.heartbeat_at = now
    task.updated_at = now
    task.finished_at = None if paused_by_batch else now
    task.error_message = "批次已暂停，可从当前阶段继续" if paused_by_batch else error
    _append_checkpoint_event(task, "paused" if paused_by_batch else "cancelled", task.current_stage, now)
    session.add(task)
    project = session.get(Project, task.project_id)
    if project:
        project.status = "created" if paused_by_batch else "cancelled"
        project.updated_at = now
        session.add(project)
    if item:
        item.status = "pending" if paused_by_batch else "failed"
        item.error_message = task.error_message
        item.finished_at = None if paused_by_batch else now
        item.updated_at = now
        session.add(item)
    session.commit()
    if batch:
        refresh_batch_status(session, batch.id)


def refresh_batch_status(session: Session, batch_id: str) -> None:
    batch = session.get(BatchJob, batch_id)
    if not batch:
        return
    items = list(
        session.exec(
            select(BatchItem).where(BatchItem.batch_id == batch_id).order_by(BatchItem.order_index)
        ).all()
    )
    batch.completed = sum(item.status == "completed" for item in items)
    batch.failed = sum(item.status == "failed" for item in items)
    unfinished = any(item.status not in {"completed", "failed"} for item in items)
    if not unfinished:
        batch.status = "completed_with_errors" if batch.failed else "completed"
        batch.finished_at = utc_now_iso()
    elif batch.status != "paused":
        running = any(item.status == "running" for item in items)
        batch.status = "running" if running else "queued"
    batch.updated_at = utc_now_iso()
    session.add(batch)
    session.commit()


def _append_checkpoint_event(
    task: TaskRun,
    event: str,
    stage: str,
    timestamp: str,
    error: str | None = None,
    *,
    checkpoint_stage: str | None = None,
    next_stage: str | None = None,
) -> None:
    try:
        checkpoint = json.loads(task.checkpoint_json)
    except (TypeError, json.JSONDecodeError):
        checkpoint = {}
    if not isinstance(checkpoint, dict):
        checkpoint = {}
    history = checkpoint.get("stage_history")
    if not isinstance(history, list):
        history = []
    entry = {"event": event, "stage": stage, "at": timestamp}
    if next_stage:
        entry["next_stage"] = next_stage
    if error:
        entry["error"] = error[-1000:]
    history.append(entry)
    checkpoint["current_stage"] = checkpoint_stage or stage
    checkpoint["stage_history"] = history[-100:]
    task.checkpoint_json = json.dumps(checkpoint, ensure_ascii=False)


def _load_batch_config(batch: BatchJob) -> dict:
    try:
        data = json.loads(batch.config_json)
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}
