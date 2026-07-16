import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session

from app.database import get_session
from app.infrastructure import process_runner as task_control
from app.services.batches import batch_service
from app.services.tasks import task_worker


logger = logging.getLogger(__name__)
router = APIRouter(tags=["batches"])


def fail(message: str, status_code: int = 400) -> None:
    raise HTTPException(status_code=status_code, detail={"success": False, "error": message})


@router.get("/batches")
def list_batches(session: Session = Depends(get_session)) -> dict:
    return {
        "success": True,
        "data": [batch_service.serialize_batch(session, batch, False) for batch in batch_service.list_batches(session)],
    }


@router.post("/batches")
def create_batch(
    scripts: list[UploadFile] = File(...),
    reference_audio: UploadFile | None = File(None),
    name: str = Form("批量生成"),
    output_dir: str = Form(...),
    media_video_dir: str = Form(""),
    include_video: bool = Form(True),
    continue_on_error: bool = Form(True),
    tts_engine: str = Form(batch_service.DEFAULT_TTS_ENGINE),
    reference_audio_text: str = Form(""),
    voice_profile_id: str = Form(""),
    auto_start: bool = Form(True),
    session: Session = Depends(get_session),
) -> dict:
    if not output_dir.strip():
        fail("请选择输出目录")
    if len(scripts) > batch_service.MAX_SCRIPT_FILES:
        fail(f"一次最多上传 {batch_service.MAX_SCRIPT_FILES} 份逐字稿")

    decoded_scripts: list[tuple[str, str]] = []
    try:
        for upload in scripts:
            filename = upload.filename or "script.txt"
            content = upload.file.read(batch_service.MAX_SCRIPT_BYTES + 1)
            decoded_scripts.append((filename, batch_service.decode_script_file(filename, content)))
        batch = batch_service.create_batch(
            session,
            name=name,
            scripts=decoded_scripts,
            reference_audio=reference_audio.file if reference_audio else None,
            reference_audio_filename=(reference_audio.filename or "reference.wav") if reference_audio else "",
            output_dir=output_dir,
            media_video_dir=media_video_dir,
            include_video=include_video,
            continue_on_error=continue_on_error,
            tts_engine=tts_engine,
            reference_audio_text=reference_audio_text,
            voice_profile_id=voice_profile_id,
        )
        if auto_start:
            batch = batch_service.start_batch(session, batch)
            task_worker.wake_worker()
        return {"success": True, "data": batch_service.serialize_batch(session, batch)}
    except (OSError, ValueError) as exc:
        logger.exception("Failed to create batch")
        fail(str(exc))


@router.get("/batches/{batch_id}")
def get_batch(batch_id: str, session: Session = Depends(get_session)) -> dict:
    batch = batch_service.get_batch(session, batch_id)
    if not batch:
        fail("Batch not found", 404)
    return {"success": True, "data": batch_service.serialize_batch(session, batch)}


@router.post("/batches/{batch_id}/start")
def start_batch(batch_id: str, session: Session = Depends(get_session)) -> dict:
    batch = batch_service.get_batch(session, batch_id)
    if not batch:
        fail("Batch not found", 404)
    try:
        batch = batch_service.start_batch(session, batch)
    except ValueError as exc:
        fail(str(exc))
    task_worker.wake_worker()
    return {"success": True, "data": batch_service.serialize_batch(session, batch)}


@router.post("/batches/{batch_id}/pause")
def pause_batch(batch_id: str, session: Session = Depends(get_session)) -> dict:
    batch = batch_service.get_batch(session, batch_id)
    if not batch:
        fail("Batch not found", 404)
    try:
        batch = batch_service.pause_batch(session, batch)
    except ValueError as exc:
        fail(str(exc))
    for item in batch_service.get_batch_items(session, batch.id):
        if item.status == "running":
            task_control.cancel(item.project_id)
    return {"success": True, "data": batch_service.serialize_batch(session, batch)}


@router.post("/batches/{batch_id}/items/{item_id}/retry")
def retry_batch_item(batch_id: str, item_id: str, session: Session = Depends(get_session)) -> dict:
    batch = batch_service.get_batch(session, batch_id)
    if not batch:
        fail("Batch not found", 404)
    try:
        item = batch_service.retry_item(session, batch, item_id)
    except ValueError as exc:
        fail(str(exc))
    task_worker.wake_worker()
    return {"success": True, "data": item}
