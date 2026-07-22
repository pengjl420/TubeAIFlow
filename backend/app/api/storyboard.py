from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.database import get_session
from app.services.narration import subtitle_service
from app.services.projects import project_service
from app.services.storyboard import storyboard_service


router = APIRouter(tags=["subtitles"])


class SrtImportRequest(BaseModel):
    content: str


@router.post("/projects/{project_id}/subtitles/import")
def import_project_srt(
    project_id: str,
    payload: SrtImportRequest,
    session: Session = Depends(get_session),
) -> dict:
    project = _require_project(session, project_id)
    try:
        return {"success": True, "data": subtitle_service.import_srt(session, project, payload.content)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": str(exc)}) from exc


@router.get("/projects/{project_id}/subtitles/cues")
def list_project_subtitle_cues(
    project_id: str,
    session: Session = Depends(get_session),
) -> dict:
    _require_project(session, project_id)
    return {"success": True, "data": subtitle_service.list_subtitle_cues(session, project_id)}


@router.get("/projects/{project_id}/storyboard")
def get_project_storyboard(
    project_id: str,
    session: Session = Depends(get_session),
) -> dict:
    _require_project(session, project_id)
    return {"success": True, "data": {"scenes": storyboard_service.list_scenes(session, project_id)}}


def _require_project(session: Session, project_id: str):
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"success": False, "error": "Project not found"})
    return project
