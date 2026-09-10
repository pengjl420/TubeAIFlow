import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
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


class TimelinePreviewJobRequest(BaseModel):
    start_ms: int = Field(default=0, ge=0)
    duration_ms: int = Field(default=30_000)


def _enqueue_scene_job(
    session: Session,
    project_id: str,
    scene_id: str,
    *,
    workflow: str,
    job_type: str,
    stage: str,
    resource_class: str,
) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"error": "Project not found"})
    from app.models.storyboard import VisualScene

    scene = session.get(VisualScene, scene_id)
    if not scene or scene.project_id != project.id:
        raise HTTPException(status_code=404, detail={"error": "Scene not found"})
    active = task_service.get_active_project_task(session, project.id)
    if active:
        raise HTTPException(status_code=409, detail={"error": "项目已有活动 Job"})
    task = task_service.enqueue_project_task(
        session,
        project,
        workflow=workflow,
        include_video=False,
        current_stage=stage,
        reuse_active=False,
        job_type=job_type,
        scene_id=scene.id,
        resource_class=resource_class,
        max_retries=2,
    )
    task_worker.wake_worker()
    return {"success": True, "data": task_service.serialize_task(session, task)}


def _enqueue_render_job(
    session: Session,
    project_id: str,
    *,
    workflow: str,
    job_type: str,
    stage: str,
    request: dict | None = None,
) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"error": "Project not found"})
    active = task_service.get_active_project_task(session, project.id)
    if active:
        raise HTTPException(status_code=409, detail={"error": "项目已有活动 Job"})
    task = task_service.enqueue_project_task(
        session,
        project,
        workflow=workflow,
        include_video=True,
        current_stage=stage,
        reuse_active=False,
        job_type=job_type,
        resource_class="ffmpeg",
        max_retries=2,
        request=request,
    )
    task_worker.wake_worker()
    return {"success": True, "data": task_service.serialize_task(session, task)}


@router.post("/projects/{project_id}/jobs/scenes/{scene_id}/images")
def enqueue_scene_image_job(
    project_id: str, scene_id: str, session: Session = Depends(get_session)
) -> dict:
    return _enqueue_scene_job(
        session, project_id, scene_id,
        workflow="scene_image_regeneration", job_type="scene_image_regeneration",
        stage="generate", resource_class="gpu",
    )


@router.post("/projects/{project_id}/jobs/scenes/{scene_id}/storyboard")
def enqueue_scene_storyboard_job(
    project_id: str, scene_id: str, session: Session = Depends(get_session)
) -> dict:
    return _enqueue_scene_job(
        session, project_id, scene_id,
        workflow="scene_storyboard_regeneration",
        job_type="scene_storyboard_regeneration",
        stage="generate", resource_class="api",
    )


@router.post("/projects/{project_id}/jobs/scenes/{scene_id}/preview")
def enqueue_scene_preview_job(
    project_id: str, scene_id: str, session: Session = Depends(get_session)
) -> dict:
    return _enqueue_scene_job(
        session, project_id, scene_id,
        workflow="scene_preview_render", job_type="scene_preview_render",
        stage="render", resource_class="ffmpeg",
    )


@router.post("/projects/{project_id}/jobs/preview")
def enqueue_timeline_preview_job(
    project_id: str,
    payload: TimelinePreviewJobRequest,
    session: Session = Depends(get_session),
) -> dict:
    if payload.duration_ms not in {30_000, 60_000}:
        raise HTTPException(status_code=400, detail={"error": "预览时长必须为 30 或 60 秒"})
    return _enqueue_render_job(
        session,
        project_id,
        workflow="timeline_preview_render",
        job_type="timeline_preview_render",
        stage="render",
        request=payload.model_dump(),
    )


@router.post("/projects/{project_id}/jobs/final-render")
def enqueue_final_render_job(
    project_id: str, session: Session = Depends(get_session)
) -> dict:
    return _enqueue_render_job(
        session,
        project_id,
        workflow="final_render",
        job_type="final_render",
        stage="scene_render",
    )


@router.post("/projects/{project_id}/jobs/assets/scan")
def enqueue_asset_scan_job(
    project_id: str, session: Session = Depends(get_session)
) -> dict:
    return _enqueue_render_job(
        session,
        project_id,
        workflow="asset_library_scan",
        job_type="asset_library_scan",
        stage="scan",
    )


@router.post("/projects/{project_id}/jobs/quality-check")
def enqueue_quality_check_job(
    project_id: str, session: Session = Depends(get_session)
) -> dict:
    return _enqueue_render_job(
        session,
        project_id,
        workflow="quality_check",
        job_type="quality_check",
        stage="analyze",
    )


@router.post("/projects/{project_id}/jobs/visual-track")
def enqueue_visual_track_job(
    project_id: str, session: Session = Depends(get_session)
) -> dict:
    return _enqueue_render_job(
        session,
        project_id,
        workflow="visual_track_render",
        job_type="visual_track_render",
        stage="render",
    )


@router.post("/projects/{project_id}/jobs/rough-cut")
def enqueue_rough_cut_job(
    project_id: str, session: Session = Depends(get_session)
) -> dict:
    return _enqueue_render_job(
        session,
        project_id,
        workflow="rough_cut_render",
        job_type="rough_cut_render",
        stage="render",
    )


@router.get("/jobs/resources")
def get_job_resources(session: Session = Depends(get_session)) -> dict:
    return {"success": True, "data": task_service.resource_snapshot(session)}


@router.get("/projects/{project_id}/jobs/{job_id}")
def get_project_job(
    project_id: str, job_id: str, session: Session = Depends(get_session)
) -> dict:
    task = session.get(TaskRun, job_id)
    if not task or task.project_id != project_id:
        raise HTTPException(status_code=404, detail={"error": "Job not found"})
    return {"success": True, "data": task_service.serialize_task(session, task)}


@router.post("/projects/{project_id}/jobs/{job_id}/pause")
def pause_project_job(
    project_id: str, job_id: str, session: Session = Depends(get_session)
) -> dict:
    task = session.get(TaskRun, job_id)
    if not task or task.project_id != project_id:
        raise HTTPException(status_code=404, detail={"error": "Job not found"})
    task_service.request_pause(session, task)
    session.commit()
    if task.cancel_requested:
        task_control.cancel(project_id)
    return {"success": True, "data": task_service.serialize_task(session, task)}


@router.post("/projects/{project_id}/jobs/{job_id}/resume")
def resume_project_job(
    project_id: str, job_id: str, session: Session = Depends(get_session)
) -> dict:
    task = session.get(TaskRun, job_id)
    if not task or task.project_id != project_id:
        raise HTTPException(status_code=404, detail={"error": "Job not found"})
    try:
        task_service.resume_task(session, task)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"error": str(exc)}) from exc
    task_worker.wake_worker()
    return {"success": True, "data": task_service.serialize_task(session, task)}


@router.post("/projects/{project_id}/jobs/{job_id}/cancel")
def cancel_project_job(
    project_id: str, job_id: str, session: Session = Depends(get_session)
) -> dict:
    task = session.get(TaskRun, job_id)
    if not task or task.project_id != project_id:
        raise HTTPException(status_code=404, detail={"error": "Job not found"})
    was_running = task.status == "running"
    task_service.request_cancel(session, task)
    session.commit()
    if was_running:
        task_control.cancel(project_id)
    return {"success": True, "data": task_service.serialize_task(session, task)}


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
    task = task_service.get_project_status_task(session, project_id)
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
    if active and active.workflow != "narration_generation":
        raise HTTPException(
            status_code=409,
            detail={"success": False, "error": "Project currently has another active Job"},
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
        project_service.VIDEO_MODE_AI_GENERATED_IMAGES,
        project_service.VIDEO_MODE_AI_LANDSCAPE_MIX,
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
