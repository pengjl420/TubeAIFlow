import threading
import uuid

from sqlalchemy import func
from sqlmodel import Session, select

from app.infrastructure.project_layout import load_project_config
from app.infrastructure.serialization import dump_json, load_json_object
from app.config import get_settings
from app.models.project import Project
from app.models.task import TaskRun
from app.domain.states import ResourceClass
from app.shared.time import elapsed_seconds, utc_now_iso
from app.workflows.builtin import get_workflow_runtime


ACTIVE_STATUSES = {"queued", "running", "paused"}
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
DEFAULT_RESOURCE_LIMITS = {
    ResourceClass.CPU.value: 4,
    ResourceClass.GPU.value: 1,
    ResourceClass.NETWORK.value: 4,
    ResourceClass.FFMPEG.value: 2,
    ResourceClass.API.value: 4,
}
_enqueue_lock = threading.Lock()
_SECRET_SUFFIXES = ("_api_key", "_token", "_secret", "_password")


def build_config_snapshot(project: Project) -> str:
    settings = {
        key: value
        for key, value in get_settings().model_dump(mode="json").items()
        if not key.lower().endswith(_SECRET_SUFFIXES)
    }
    return dump_json(
        {
            "format_version": 1,
            "project": load_project_config(project),
            "settings": settings,
        }
    )


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
    job_type: str = "project_workflow",
    scene_id: str | None = None,
    resource_class: str = ResourceClass.CPU.value,
    max_retries: int = 0,
    request: dict | None = None,
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
            job_type=job_type,
            scene_id=scene_id,
            resource_class=ResourceClass(resource_class).value,
            status=initial_status,
            current_stage=current_stage,
            include_video=include_video,
            max_retries=max(0, max_retries),
            request_json=dump_json(request or {}),
            queue_sequence=int(last_sequence or 0) + 1,
            checkpoint_json=dump_json(
                {"current_stage": current_stage, "stage_history": []}
            ),
            config_snapshot_json=build_config_snapshot(project),
            created_at=now,
            updated_at=now,
        )
        session.add(task)
        if initial_status == "queued" and job_type in {"project_workflow", "final_render"}:
            project.status = (
                "video_in_progress"
                if _is_video_task(workflow, current_stage)
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
    checkpoint = load_json_object(task.checkpoint_json)
    history = checkpoint.get("stage_history")
    if not isinstance(history, list):
        history = []
    history.append({"event": "resumed", "stage": current_stage, "at": now})
    checkpoint["current_stage"] = current_stage
    checkpoint["stage_history"] = history[-100:]
    task.checkpoint_json = dump_json(checkpoint)
    session.add(task)

    project = session.get(Project, task.project_id)
    if project:
        project.status = (
            "video_in_progress"
            if _is_video_task(task.workflow, current_stage)
            else "narration_in_progress"
        )
        project.updated_at = now
        session.add(project)

    session.commit()
    session.refresh(task)


def _is_video_task(workflow: str, current_stage: str) -> bool:
    try:
        return current_stage in get_workflow_runtime(workflow).video_stages
    except ValueError:
        return False


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


def get_next_runnable_task(
    session: Session, limits: dict[str, int] | None = None
) -> TaskRun | None:
    configured = {**DEFAULT_RESOURCE_LIMITS, **(limits or {})}
    running_counts = {
        resource: int(count)
        for resource, count in session.exec(
            select(TaskRun.resource_class, func.count(TaskRun.id))
            .where(TaskRun.status == "running")
            .group_by(TaskRun.resource_class)
        ).all()
    }
    queued = session.exec(
        select(TaskRun)
        .where(TaskRun.status == "queued")
        .order_by(TaskRun.queue_sequence, TaskRun.created_at, TaskRun.id)
    ).all()
    return next(
        (
            task
            for task in queued
            if running_counts.get(task.resource_class, 0)
            < max(0, configured.get(task.resource_class, 1))
        ),
        None,
    )


def resource_snapshot(session: Session, limits: dict[str, int] | None = None) -> dict:
    configured = {**DEFAULT_RESOURCE_LIMITS, **(limits or {})}
    rows = session.exec(
        select(TaskRun.resource_class, TaskRun.status, func.count(TaskRun.id))
        .where(TaskRun.status.in_(["queued", "running"]))
        .group_by(TaskRun.resource_class, TaskRun.status)
    ).all()
    counts = {(resource, status): int(count) for resource, status, count in rows}
    return {
        resource: {
            "limit": limit,
            "running": counts.get((resource, "running"), 0),
            "queued": counts.get((resource, "queued"), 0),
        }
        for resource, limit in configured.items()
    }


def queue_paused_task(session: Session, task: TaskRun) -> None:
    now = utc_now_iso()
    with _enqueue_lock:
        last_sequence = session.exec(select(func.max(TaskRun.queue_sequence))).one()
        task.status = "queued"
        task.queue_sequence = int(last_sequence or 0) + 1
        task.cancel_requested = False
        task.pause_requested = False
        task.error_message = None
        task.error_code = None
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


def request_pause(session: Session, task: TaskRun) -> None:
    now = utc_now_iso()
    if task.status == "queued":
        task.status = "paused"
    elif task.status == "running":
        task.pause_requested = True
        task.cancel_requested = True
    task.updated_at = now
    session.add(task)


def resume_task(session: Session, task: TaskRun) -> None:
    if task.status not in {"paused", "failed"}:
        raise ValueError("Only paused or failed Jobs can be resumed")
    if task.status == "failed" and task.attempt_count > task.max_retries:
        raise ValueError("Job retry limit has been reached")
    queue_paused_task(session, task)
    session.commit()
    session.refresh(task)


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
            "result": load_json_object(task.result_json),
            "request": load_json_object(task.request_json),
        }
    )
    return data
