import json

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.database import get_session
from app.config import get_settings
from app.infrastructure import process_runner as task_control
from app.infrastructure.project_layout import get_project_work_dir, load_project_config
from app.integrations.tts.runner_io import write_json
from app.models.batch import BatchItem
from app.models.task import TaskRun
from app.services.projects import project_service
from app.services.tasks import task_service, task_worker
from app.shared.time import utc_now_iso
from app.workflows import narration_generation, video_synthesis


router = APIRouter(tags=["tasks"])


@router.post("/projects/{project_id}/tasks/cancel")
def cancel_project_task(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"success": False, "error": "Project not found"})
    task = task_service.get_active_project_task(session, project_id)
    if not task:
        latest_video = _latest_ai_video_task(session, project_id)
        if latest_video and latest_video.status == "review_required":
            task = latest_video
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
    latest = task_service.get_latest_project_workflow_task(
        session, project_id, "narration_generation"
    )
    if latest and latest.status == "failed":
        task_service.resume_failed_task(
            session,
            latest,
            current_stage=latest.current_stage or "segmenting",
        )
        task_worker.wake_worker()
        return {"success": True, "data": task_service.serialize_task(session, latest)}
    try:
        initial_stage = narration_generation.initial_stage(
            session,
            project,
            include_video=bool(config.get("include_video", False)),
        )
        task = task_service.enqueue_project_task(
            session,
            project,
            include_video=bool(config.get("include_video", False)),
            current_stage=initial_stage,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": str(exc)}) from exc
    task_worker.wake_worker()
    return {"success": True, "data": task_service.serialize_task(session, task)}


@router.post("/projects/{project_id}/workflows/continue")
def continue_project_workflow(project_id: str, session: Session = Depends(get_session)) -> dict:
    """Continue every remaining configured stage from the earliest missing artifact."""
    return start_project_workflow(project_id, session)


@router.post("/projects/{project_id}/workflows/video/start")
def start_video_workflow(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"success": False, "error": "Project not found"})
    if project_service.get_project_video_mode(project) not in {
        project_service.VIDEO_MODE_AI_SEMANTIC,
        project_service.VIDEO_MODE_AI_GENERATED_IMAGES,
    }:
        raise HTTPException(
            status_code=409,
            detail={"success": False, "error": "当前项目未启用 AI 语义视频生成"},
        )
    if not video_synthesis.has_subtitles(session, project_id):
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": "请先完成配音字幕流程或导入 SRT"},
        )
    active = task_service.get_active_project_task(session, project_id)
    if active:
        if active.workflow != "video_synthesis":
            raise HTTPException(
                status_code=409,
                detail={"success": False, "error": "项目当前有其他生成任务正在执行"},
            )
        return {"success": True, "data": task_service.serialize_task(session, active)}

    latest = _latest_ai_video_task(session, project_id)
    if latest and latest.status == "failed":
        task_service.resume_failed_task(
            session,
            latest,
            current_stage=latest.current_stage or video_synthesis.initial_stage(session, project_id),
        )
        task = latest
    elif latest and latest.status == "review_required":
        resume_stage = video_synthesis.initial_stage(session, project_id)
        if resume_stage in {"storyboard", "asset_search"}:
            pass
        elif latest.current_stage in {"asset_review", "image_review"}:
            missing = video_synthesis.assignment_gap(session, project_id)
            if missing:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "success": False,
                        "error": f"仍有 {missing} 个场景未确认素材，请先完成素材审核",
                    },
                )
            resume_stage = latest.current_stage
        else:
            resume_stage = "scene_render"
        task_service.resume_review_task(session, latest, current_stage=resume_stage)
        task = latest
    else:
        task = task_service.enqueue_project_task(
            session,
            project,
            workflow="video_synthesis",
            include_video=True,
            current_stage=video_synthesis.initial_stage(session, project_id),
        )
    task_worker.wake_worker()
    return {"success": True, "data": task_service.serialize_task(session, task)}


@router.get("/projects/{project_id}/workflows/video/status")
def video_workflow_status(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"success": False, "error": "Project not found"})
    task = _latest_ai_video_task(session, project_id)
    return {"success": True, "data": task_service.serialize_task(session, task)}


def _latest_ai_video_task(session: Session, project_id: str) -> TaskRun | None:
    """Include full-generation tasks after they have entered the AI video stages."""
    task = task_service.get_latest_project_workflow_task(session, project_id, "video_synthesis")
    full_task = task_service.get_latest_project_workflow_task(
        session, project_id, "narration_generation"
    )
    if full_task and full_task.current_stage in video_synthesis.STAGES:
        if task is None or full_task.queue_sequence > task.queue_sequence:
            return full_task
    return task


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
                write_json(path, data)
        except (OSError, json.JSONDecodeError):
            pass
