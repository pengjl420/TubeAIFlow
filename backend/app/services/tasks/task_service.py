import json
import threading
import uuid

from sqlalchemy import func
from sqlmodel import Session, select

from app.infrastructure.project_layout import load_project_config
from app.models.project import Project
from app.models.task import TaskRun
from app.shared.time import elapsed_seconds, utc_now_iso


ACTIVE_STATUSES = {"queued", "running", "paused"}
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
_enqueue_lock = threading.Lock()


def enqueue_project_task(
    session: Session,
    project: Project,
    *,
    include_video: bool,
    workflow: str = "narration_generation",
    current_stage: str = "segmenting",
    batch_id: str | None = None,
    batch_item_id: str | None = None,
    initial_status: str = "queued",
    reuse_active: bool = True,
    commit: bool = True,
) -> TaskRun:
    if initial_status not in {"queued", "paused"}:
        raise ValueError(f"Unsupported initial task status: {initial_status}")
    with _enqueue_lock:
        if reuse_active:
            active = get_active_project_task(session, project.id)
            if active:
                return active
        now = utc_now_iso()
        last_sequence = session.exec(select(func.max(TaskRun.queue_sequence))).one()
        task = TaskRun(
            id=uuid.uuid4().hex[:16],
            project_id=project.id,
            batch_id=batch_id,
            batch_item_id=batch_item_id,
            workflow=workflow,
            status=initial_status,
            current_stage=current_stage,
            include_video=include_video,
            queue_sequence=int(last_sequence or 0) + 1,
            checkpoint_json=json.dumps(
                {"current_stage": current_stage, "stage_history": []},
                ensure_ascii=False,
            ),
            config_snapshot_json=json.dumps(load_project_config(project), ensure_ascii=False),
            created_at=now,
            updated_at=now,
        )
        session.add(task)
        if initial_status == "queued":
            project.status = (
                "video_in_progress"
                if workflow == "video_synthesis" or current_stage == "video"
                else "narration_in_progress"
            )
            project.updated_at = now
            session.add(project)
        session.flush()
        if commit:
            session.commit()
            session.refresh(task)
    return task


def get_latest_project_task(session: Session, project_id: str) -> TaskRun | None:
    return session.exec(
        select(TaskRun)
        .where(TaskRun.project_id == project_id)
        .order_by(TaskRun.queue_sequence.desc())
    ).first()


def get_latest_project_workflow_task(
    session: Session, project_id: str, workflow: str
) -> TaskRun | None:
    return session.exec(
        select(TaskRun)
        .where(TaskRun.project_id == project_id, TaskRun.workflow == workflow)
        .order_by(TaskRun.queue_sequence.desc())
    ).first()


def resume_failed_task(session: Session, task: TaskRun, *, current_stage: str) -> None:
    """Requeue a failed task from a verified workflow checkpoint."""
    if task.status != "failed":
        raise ValueError("当前任务不处于失败状态")

    now = utc_now_iso()
    task.current_stage = current_stage
    queue_paused_task(session, task)
    try:
        checkpoint = json.loads(task.checkpoint_json or "{}")
    except json.JSONDecodeError:
        checkpoint = {}
    history = checkpoint.get("stage_history")
    if not isinstance(history, list):
        history = []
    history.append({"event": "resumed", "stage": current_stage, "at": now})
    checkpoint["current_stage"] = current_stage
    checkpoint["stage_history"] = history[-100:]
    task.checkpoint_json = json.dumps(checkpoint, ensure_ascii=False)
    session.add(task)

    project = session.get(Project, task.project_id)
    if project:
        project.status = (
            "video_in_progress"
            if task.workflow == "video_synthesis" or current_stage == "video"
            else "narration_in_progress"
        )
        project.updated_at = now
        session.add(project)

    session.commit()
    session.refresh(task)


def get_active_project_task(session: Session, project_id: str) -> TaskRun | None:
    return session.exec(
        select(TaskRun)
        .where(TaskRun.project_id == project_id, TaskRun.status.in_(ACTIVE_STATUSES))
        .order_by(TaskRun.queue_sequence.desc())
    ).first()


def get_latest_batch_item_task(session: Session, batch_item_id: str) -> TaskRun | None:
    return session.exec(
        select(TaskRun)
        .where(TaskRun.batch_item_id == batch_item_id)
        .order_by(TaskRun.queue_sequence.desc())
    ).first()


def list_batch_tasks(session: Session, batch_id: str) -> list[TaskRun]:
    return list(
        session.exec(
            select(TaskRun)
            .where(TaskRun.batch_id == batch_id)
            .order_by(TaskRun.queue_sequence)
        ).all()
    )


def queue_paused_task(session: Session, task: TaskRun) -> None:
    now = utc_now_iso()
    with _enqueue_lock:
        last_sequence = session.exec(select(func.max(TaskRun.queue_sequence))).one()
        task.status = "queued"
        task.queue_sequence = int(last_sequence or 0) + 1
        task.cancel_requested = False
        task.error_message = None
        task.lease_owner = None
        task.heartbeat_at = None
        task.finished_at = None
        task.updated_at = now
        session.add(task)
        session.flush()


def pause_queued_task(session: Session, task: TaskRun) -> None:
    if task.status != "queued":
        return
    task.status = "paused"
    task.updated_at = utc_now_iso()
    session.add(task)


def request_cancel(session: Session, task: TaskRun) -> None:
    now = utc_now_iso()
    if task.status == "queued":
        task.status = "cancelled"
        task.finished_at = now
    elif task.status == "running":
        task.cancel_requested = True
    elif task.status == "paused":
        task.status = "cancelled"
        task.finished_at = now
    task.updated_at = now
    session.add(task)


def serialize_task(session: Session, task: TaskRun | None) -> dict:
    if task is None:
        return {
            "id": None,
            "status": "idle",
            "running": False,
            "queued": False,
            "stage": None,
            "cancelled": False,
            "queue_position": None,
        }
    queue_position = None
    if task.status == "queued":
        ahead = session.exec(
            select(func.count(TaskRun.id)).where(
                TaskRun.status == "queued",
                TaskRun.queue_sequence < task.queue_sequence,
            )
        ).one()
        running = session.exec(
            select(func.count(TaskRun.id)).where(TaskRun.status == "running")
        ).one()
        queue_position = int(ahead or 0) + int(running or 0) + 1
    data = task.model_dump()
    data.update(
        {
            "running": task.status == "running",
            "queued": task.status == "queued",
            "stage": task.current_stage,
            "cancelled": task.status == "cancelled" or task.cancel_requested,
            "queue_position": queue_position,
            "workflow_duration_seconds": elapsed_seconds(task.started_at, task.finished_at),
        }
    )
    return data
