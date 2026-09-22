from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.database import get_session
from app.services.projects import project_service
from app.services.quality import qa_service
from pydantic import BaseModel


router = APIRouter(tags=["quality"])


class ManualAcceptanceRequest(BaseModel):
    editor: str
    editor_version: str = ""
    checked_by: str | None = None
    audio_ok: bool
    subtitles_ok: bool
    media_links_ok: bool
    notes: str = ""


@router.post("/projects/{project_id}/quality/check")
def run_quality_check(project_id: str, session: Session = Depends(get_session)) -> dict:
    from app.api.tasks import enqueue_quality_check_job

    return enqueue_quality_check_job(project_id, session)


@router.get("/projects/{project_id}/quality/report")
def get_quality_report(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = _require_project(session, project_id)
    report = qa_service.read_report(project, session)
    if report is None:
        raise HTTPException(status_code=404, detail={"success": False, "error": "QA 报告尚未生成"})
    return {"success": True, "data": report}


@router.post("/projects/{project_id}/quality/manual-acceptance")
def save_manual_acceptance(
    project_id: str,
    payload: ManualAcceptanceRequest,
    session: Session = Depends(get_session),
) -> dict:
    project = _require_project(session, project_id)
    try:
        report = qa_service.record_manual_acceptance(
            session,
            project,
            **payload.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"error": str(exc)}) from exc
    return {"success": True, "data": report}


def _require_project(session: Session, project_id: str):
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(
            status_code=404, detail={"success": False, "error": "Project not found"}
        )
    return project
