from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.database import get_session
from app.infrastructure import process_runner as task_control
from app.services.narration import srt_service, timeline_service
from app.services.projects import project_service


router = APIRouter(tags=["subtitles"])


@router.post("/projects/{project_id}/timeline")
def create_timeline(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"success": False, "error": "Project not found"})
    return {"success": True, "data": timeline_service.build_timeline(session, project)}


@router.post("/projects/{project_id}/subtitles/srt")
def create_srt(
    project_id: str,
    session: Session = Depends(get_session),
) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"success": False, "error": "Project not found"})
    try:
        with task_control.controlled(project_id, "subtitles"):
            project = project_service.ensure_output_filename(session, project)
            segments = timeline_service.build_timeline(session, project)["segments"]
            srt_path = srt_service.create_full_srt(
                project,
                _load_segments_for_srt(session, project.id),
                session=session,
            )
            project.status = "narration_ready"
            project.updated_at = datetime.utcnow().isoformat()
            session.add(project)
            session.commit()
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": str(exc)}) from exc
    return {
        "success": True,
        "data": {
            "srt_path": str(srt_path),
            "segments": len(segments),
        },
    }


def _load_segments_for_srt(session: Session, project_id: str):
    from sqlmodel import select

    from app.models.narration import Segment

    return session.exec(
        select(Segment)
        .where(Segment.project_id == project_id)
        .order_by(Segment.segment_index)
    ).all()
