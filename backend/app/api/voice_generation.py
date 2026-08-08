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
