import json

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.database import get_session
from app.config import get_settings
from app.infrastructure import process_runner as task_control
from app.infrastructure.project_layout import get_project_work_dir
from app.infrastructure.project_layout import load_project_config
from app.models.batch import BatchItem
from app.models.task import TaskRun
from app.services.projects import project_service
from app.services.tasks import task_service, task_worker
from app.shared.time import utc_now_iso


router = APIRouter(tags=["tasks"])


@router.post("/projects/{project_id}/tasks/cancel")
def cancel_project_task(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"success": False, "error": "Project not found"})
    task = task_service.get_active_project_task(session, project_id)
    if task:
        was_running = task.status == "running"
        task_service.request_cancel(session, task)
        if task.status == "cancelled":
            project.status = "cancelled"
            project.updated_at = utc_now_iso()
            session.add(project)
            if task.batch_item_id:
                item = session.get(BatchItem, task.batch_item_id)
                if item:
                    item.status = "failed"
                    item.error_message = "任务已由用户取消"
                    item.finished_at = utc_now_iso()
                    item.updated_at = item.finished_at
                    session.add(item)
        session.commit()
        if was_running:
            task_control.cancel(project_id)
        if task.batch_id and task.status == "cancelled":
            task_worker.refresh_batch_status(session, task.batch_id)
        _mark_progress_cancelled(project)
        return {
            "success": True,
            "data": {"cancelled": True, "stage": task.current_stage, "task_id": task.id},
        }

    result = task_control.cancel(project_id)
    if result["cancelled"]:
        project.status = "cancelled"
        project.updated_at = utc_now_iso()
        session.add(project)
        session.commit()
        _mark_progress_cancelled(project)
    return {"success": True, "data": result}


@router.get("/projects/{project_id}/tasks/status")
def project_task_status(project_id: str, session: Session = Depends(get_session)) -> dict:
    if not project_service.get_project(session, project_id):
        raise HTTPException(status_code=404, detail={"success": False, "error": "Project not found"})
    task = task_service.get_latest_project_task(session, project_id)
    data = task_service.serialize_task(session, task)
    runtime = task_control.status(project_id)
    if runtime["running"] and (task is None or task.status in task_service.TERMINAL_STATUSES):
        data.update(runtime)
        data["status"] = "running"
        data["stage"] = runtime["stage"]
    return {"success": True, "data": data}


@router.post("/projects/{project_id}/workflows/narration/start")
def start_project_workflow(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"success": False, "error": "Project not found"})
    if not project.script_clean_path:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": "Project script must be saved before generation"},
        )
    project = project_service.ensure_output_filename(session, project)
    config = load_project_config(project)
    active = task_service.get_active_project_task(session, project_id)
    if active and active.status == "paused":
        raise HTTPException(
            status_code=409,
            detail={
                "success": False,
                "error": "Project belongs to a paused task; resume its batch before starting it again",
            },
        )
    try:
        task = task_service.enqueue_project_task(
            session,
            project,
            include_video=bool(config.get("include_video", False)),
            current_stage="segmenting",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": str(exc)}) from exc
    task_worker.wake_worker()
    return {"success": True, "data": task_service.serialize_task(session, task)}


@router.get("/tasks")
def list_tasks(session: Session = Depends(get_session)) -> dict:
    tasks = list(
        session.exec(select(TaskRun).order_by(TaskRun.queue_sequence.desc()).limit(100)).all()
    )
    return {"success": True, "data": [task_service.serialize_task(session, task) for task in tasks]}


def _mark_progress_cancelled(project) -> None:
    base_dir = get_project_work_dir(project, get_settings().workspace_dir)
    for path in (base_dir / "logs" / "tts_progress.json", base_dir / "video" / "progress.json"):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("status") == "running":
                data["status"] = "cancelled"
                data["message"] = "Task was stopped by the user"
                temp_path = path.with_suffix(path.suffix + ".tmp")
                temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                temp_path.replace(path)
        except (OSError, json.JSONDecodeError):
            pass
