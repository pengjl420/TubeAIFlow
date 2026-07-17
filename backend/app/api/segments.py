from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from app.config import get_settings
from app.database import get_session
from app.models.narration import Segment
from app.infrastructure.file_storage import ensure_inside_any, project_dir
from app.infrastructure.project_layout import get_project_output_dir, get_project_work_dir
from app.services.projects import project_service
from app.shared.time import utc_now_iso


router = APIRouter(tags=["segments"])


class SegmentUpdateRequest(BaseModel):
    text: str | None = None


@router.get("/projects/{project_id}/segments")
def list_segments(project_id: str, session: Session = Depends(get_session)) -> dict:
    segments = session.exec(
        select(Segment)
        .where(Segment.project_id == project_id)
        .order_by(Segment.segment_index)
    ).all()
    return {"success": True, "data": segments}


@router.put("/projects/{project_id}/segments/{segment_id}")
def update_segment(
    project_id: str,
    segment_id: str,
    payload: SegmentUpdateRequest,
    session: Session = Depends(get_session),
) -> dict:
    segment = session.exec(
        select(Segment).where(
            Segment.project_id == project_id,
            Segment.segment_id == segment_id,
        )
    ).first()
    if not segment:
        raise HTTPException(status_code=404, detail={"success": False, "error": "Segment not found"})
    if payload.text is not None:
        segment.text = payload.text
        segment.status = "pending"
        segment.error_message = None
    segment.updated_at = utc_now_iso()
    session.add(segment)
    session.commit()
    session.refresh(segment)
    return {"success": True, "data": segment}


@router.get("/projects/{project_id}/segments/{segment_id}/audio")
def get_segment_audio(project_id: str, segment_id: str, session: Session = Depends(get_session)) -> FileResponse:
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"success": False, "error": "Project not found"})
    segment = session.exec(
        select(Segment).where(
            Segment.project_id == project_id,
            Segment.segment_id == segment_id,
        )
    ).first()
    if not segment:
        raise HTTPException(status_code=404, detail={"success": False, "error": "Segment audio not found"})

    audio_path = (
        Path(segment.audio_path)
        if segment.audio_path
        else get_project_work_dir(project, get_settings().workspace_dir) / "audio" / "segments" / f"{segment_id}.wav"
    )
    try:
        audio_path = ensure_inside_any(
            audio_path,
            [
                get_project_work_dir(project, get_settings().workspace_dir),
                get_project_output_dir(project, get_settings().workspace_dir),
                project_dir(get_settings().workspace_dir, project_id),
            ],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": str(exc)}) from exc
    if not audio_path.is_file():
        raise HTTPException(status_code=404, detail={"success": False, "error": "Segment audio file does not exist"})
    return FileResponse(audio_path)
