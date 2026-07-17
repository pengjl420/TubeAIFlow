from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.database import get_session
from app.services.projects import project_service
from app.services.quality import qa_service


router = APIRouter(tags=["quality"])


@router.post("/projects/{project_id}/quality/check")
def run_quality_check(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = _require_project(session, project_id)
    try:
        data = qa_service.run_quality_check(session, project)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": str(exc)}) from exc
    return {"success": True, "data": data}


@router.get("/projects/{project_id}/quality/report")
def get_quality_report(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = _require_project(session, project_id)
    report = qa_service.read_report(project)
    if report is None:
        raise HTTPException(status_code=404, detail={"success": False, "error": "QA 报告尚未生成"})
    return {"success": True, "data": report}


def _require_project(session: Session, project_id: str):
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"success": False, "error": "Project not found"})
    return project
