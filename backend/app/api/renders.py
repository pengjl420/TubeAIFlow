from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.database import get_session
from app.infrastructure import process_runner as task_control
from app.services.projects import project_service
from app.services.rendering import rough_cut_service


router = APIRouter(tags=["videos"])


class VideoSettingsRequest(BaseModel):
    media_video_dir: str


@router.post("/projects/{project_id}/video/settings")
def save_video_settings(
    project_id: str,
    payload: VideoSettingsRequest,
    session: Session = Depends(get_session),
) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"success": False, "error": "Project not found"})
    try:
        return {
            "success": True,
            "data": rough_cut_service.save_video_settings(session, project, payload.media_video_dir),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": str(exc)}) from exc


@router.post("/projects/{project_id}/video/compose")
def compose_video(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"success": False, "error": "Project not found"})
    try:
        project = project_service.ensure_output_filename(session, project)
        with task_control.controlled(project_id, "video"):
            path = rough_cut_service.compose_video(session, project)
        return {"success": True, "data": {"path": str(path)}}
    except rough_cut_service.VideoCompositionRunningError as exc:
        raise HTTPException(status_code=409, detail={"success": False, "error": str(exc)}) from exc
    except task_control.TaskCancelledError as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": str(exc)}) from exc
    except (ValueError, RuntimeError, OSError) as exc:
        try:
            rough_cut_service.mark_video_progress_failed(project, str(exc))
        except OSError:
            # Preserve the original composition error if the progress file is
            # itself temporarily unavailable.
            pass
        raise HTTPException(status_code=400, detail={"success": False, "error": str(exc)}) from exc


@router.get("/projects/{project_id}/video/status")
def video_status(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"success": False, "error": "Project not found"})
    return {"success": True, "data": rough_cut_service.read_video_progress(project)}
