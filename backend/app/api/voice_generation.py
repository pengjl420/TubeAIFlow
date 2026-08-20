from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.database import get_session
from app.models.voice_generation import VoiceGenerationTask
from app.services.narration import voice_generation_queue


router = APIRouter(prefix="/tools/voice-generation", tags=["voice-generation"])


class VoiceGenerationRequest(BaseModel):
    voice_profile_id: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=50000)
    output_filename: str = Field(min_length=1, max_length=200)


@router.post("/tasks")
def create_task(payload: VoiceGenerationRequest, session: Session = Depends(get_session)) -> dict:
    try:
        task = voice_generation_queue.enqueue(
            session,
            voice_profile_id=payload.voice_profile_id,
            text=payload.text,
            output_filename=payload.output_filename,
        )
        data = voice_generation_queue.serialize_task(session, task)
        voice_generation_queue.wake_worker()
        return {"success": True, "data": data}
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": str(exc)}) from exc


@router.get("/tasks")
def list_tasks(limit: int = Query(default=100, ge=1, le=500), session: Session = Depends(get_session)) -> dict:
    return {"success": True, "data": voice_generation_queue.list_tasks(session, limit)}


def _get_task_or_404(session: Session, task_id: str) -> VoiceGenerationTask:
    task = session.get(VoiceGenerationTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail={"success": False, "error": "配音任务不存在"})
    return task


@router.post("/tasks/{task_id}/pause")
def pause_task(task_id: str, session: Session = Depends(get_session)) -> dict:
    try:
        task = voice_generation_queue.pause_task(session, _get_task_or_404(session, task_id))
        return {"success": True, "data": voice_generation_queue.serialize_task(session, task)}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"success": False, "error": str(exc)}) from exc


@router.post("/tasks/{task_id}/resume")
def resume_task(task_id: str, session: Session = Depends(get_session)) -> dict:
    try:
        task = voice_generation_queue.resume_task(session, _get_task_or_404(session, task_id))
        data = voice_generation_queue.serialize_task(session, task)
        voice_generation_queue.wake_worker()
        return {"success": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"success": False, "error": str(exc)}) from exc


@router.delete("/tasks/{task_id}")
def delete_task(task_id: str, session: Session = Depends(get_session)) -> dict:
    try:
        recycled = voice_generation_queue.delete_task(session, _get_task_or_404(session, task_id))
        return {"success": True, "data": {"id": task_id, "recycled_paths": recycled}}
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail={"success": False, "error": str(exc)}) from exc


@router.get("/tasks/{task_id}/audio")
def get_audio(task_id: str, download: bool = False, session: Session = Depends(get_session)):
    task = session.get(VoiceGenerationTask, task_id)
    if not task or task.status != "completed" or not task.output_path:
        raise HTTPException(status_code=404, detail={"success": False, "error": "配音文件不存在"})
    path = Path(task.output_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail={"success": False, "error": "配音文件已被移动或删除"})
    disposition = "attachment" if download else "inline"
    return FileResponse(path, media_type="audio/wav", filename=task.output_filename,
                        content_disposition_type=disposition)


@router.get("/tasks/{task_id}/segments/{segment_index}/audio")
def get_segment_audio(
    task_id: str,
    segment_index: int,
    download: bool = False,
    session: Session = Depends(get_session),
):
    task = session.get(VoiceGenerationTask, task_id)
    if not task or task.status != "completed" or segment_index < 1:
        raise HTTPException(status_code=404, detail={"success": False, "error": "分段音频不存在"})
    filename = f"{Path(task.output_filename).stem}_{segment_index:04d}.wav"
    path = Path(task.output_path).parent / "segments" / filename if task.output_path else Path()
    if not path.is_file():
        raise HTTPException(status_code=404, detail={"success": False, "error": "分段音频不存在"})
    disposition = "attachment" if download else "inline"
    return FileResponse(path, media_type="audio/wav", filename=filename,
                        content_disposition_type=disposition)
