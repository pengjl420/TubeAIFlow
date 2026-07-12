from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.database import get_session
from app.services import project_service, video_service


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
            "data": video_service.save_video_settings(session, project, payload.media_video_dir),
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
        path = video_service.compose_silent_video(session, project)
        return {"success": True, "data": {"path": str(path)}}
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": str(exc)}) from exc
