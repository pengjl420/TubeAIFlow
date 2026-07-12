from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from app.config import get_settings
from app.database import get_session
from app.models.segment import Segment
from app.services import project_service
from app.utils.file_utils import ensure_inside_workspace, project_dir
from app.utils.project_paths import get_project_output_dir, get_project_work_dir


router = APIRouter(tags=["segments"])


class SegmentUpdateRequest(BaseModel):
    text_zh: str | None = None
    text_en: str | None = None


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
    if payload.text_zh is not None:
        segment.text_zh = payload.text_zh
        segment.status = "pending"
        segment.error_message = None
    if payload.text_en is not None:
        segment.text_en = payload.text_en
    segment.updated_at = datetime.utcnow().isoformat()
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
    if not segment or not segment.audio_path:
        raise HTTPException(status_code=404, detail={"success": False, "error": "Segment audio not found"})

    audio_path = Path(segment.audio_path)
    try:
        try:
            audio_path = ensure_inside_workspace(audio_path, get_project_work_dir(project, get_settings().workspace_dir))
        except ValueError:
            try:
                audio_path = ensure_inside_workspace(audio_path, get_project_output_dir(project, get_settings().workspace_dir))
            except ValueError:
                audio_path = ensure_inside_workspace(audio_path, project_dir(get_settings().workspace_dir, project_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": str(exc)}) from exc
    if not audio_path.is_file():
        raise HTTPException(status_code=404, detail={"success": False, "error": "Segment audio file does not exist"})
    return FileResponse(audio_path)
