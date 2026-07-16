import json

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.database import get_session
from app.config import get_settings
from app.infrastructure import process_runner as task_control
from app.infrastructure.project_layout import get_project_work_dir
from app.services.projects import project_service
from app.shared.time import utc_now_iso


router = APIRouter(tags=["tasks"])


@router.post("/projects/{project_id}/tasks/cancel")
def cancel_project_task(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"success": False, "error": "Project not found"})
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
    return {"success": True, "data": task_control.status(project_id)}


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
