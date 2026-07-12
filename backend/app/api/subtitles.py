from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.database import get_session
from app.services import ass_service, project_service, timeline_service, translate_service


router = APIRouter(tags=["subtitles"])


@router.post("/projects/{project_id}/timeline")
def create_timeline(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"success": False, "error": "Project not found"})
    return {"success": True, "data": timeline_service.build_timeline(session, project)}


@router.post("/projects/{project_id}/subtitles/zh")
def create_zh_ass(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"success": False, "error": "Project not found"})
    path = ass_service.create_ass(project, "zh")
    return {"success": True, "data": {"path": str(path)}}


@router.post("/projects/{project_id}/subtitles/en")
def create_en_ass(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"success": False, "error": "Project not found"})
    translate_service.save_empty_translation(session, project)
    path = ass_service.create_ass(project, "en")
    return {"success": True, "data": {"path": str(path)}}
