from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.database import get_session
from app.services import audio_service, export_service, project_service, task_control


router = APIRouter(tags=["exports"])


@router.post("/projects/{project_id}/audio/merge")
def merge_audio(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"success": False, "error": "Project not found"})
    try:
        project = project_service.ensure_output_filename(session, project)
        with task_control.controlled(project_id, "audio_merge"):
            path = audio_service.merge_project_audio(session, project)
        return {"success": True, "data": {"path": str(path)}}
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": str(exc)},
        ) from exc


@router.post("/projects/{project_id}/audio/durations")
def update_durations(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"success": False, "error": "Project not found"})
    project = project_service.ensure_output_filename(session, project)
    return {"success": True, "data": audio_service.update_segment_durations(session, project)}


@router.post("/projects/{project_id}/export")
def export_project(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"success": False, "error": "Project not found"})
    project = project_service.ensure_output_filename(session, project)
    path = export_service.create_manifest(project)
    return {"success": True, "data": {"path": str(path)}}
