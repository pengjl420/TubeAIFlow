import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session

from app.config import get_settings
from app.database import get_session
from app.infrastructure.file_storage import ensure_inside_any
from app.services.narration import voice_profile_service


router = APIRouter(tags=["voices"])
logger = logging.getLogger(__name__)


def fail(message: str, status_code: int = 400) -> None:
    raise HTTPException(status_code=status_code, detail={"success": False, "error": message})


@router.get("/voices")
def list_voices(session: Session = Depends(get_session)) -> dict:
    return {"success": True, "data": voice_profile_service.list_profiles(session)}


@router.post("/voices")
def create_voice(
    name: str = Form(...),
    tts_engine: str = Form("qwen3_tts"),
    reference_audio_text: str = Form(""),
    cosyvoice_speed: float = Form(1.0),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> dict:
    try:
        profile = voice_profile_service.create_profile(
            session,
            name=name,
            tts_engine=tts_engine,
            reference_audio_text=reference_audio_text,
            cosyvoice_speed=cosyvoice_speed,
            source=file.file,
            original_filename=file.filename or "reference.wav",
        )
        return {"success": True, "data": voice_profile_service.serialize_profile(profile)}
    except (OSError, ValueError) as exc:
        logger.exception("Failed to create voice profile")
        fail(str(exc))


@router.put("/voices/{profile_id}")
def update_voice(
    profile_id: str,
    name: str = Form(...),
    tts_engine: str = Form("qwen3_tts"),
    reference_audio_text: str = Form(""),
    cosyvoice_speed: float | None = Form(None),
    file: UploadFile | None = File(None),
    session: Session = Depends(get_session),
) -> dict:
    profile = voice_profile_service.get_profile(session, profile_id)
    if not profile:
        fail("音色不存在", 404)
    try:
        profile = voice_profile_service.update_profile(
            session,
            profile,
            name=name,
            tts_engine=tts_engine,
            reference_audio_text=reference_audio_text,
            cosyvoice_speed=cosyvoice_speed,
            source=file.file if file else None,
            original_filename=file.filename if file else None,
        )
        return {"success": True, "data": voice_profile_service.serialize_profile(profile)}
    except (OSError, ValueError) as exc:
        logger.exception("Failed to update voice profile %s", profile_id)
        fail(str(exc))


@router.get("/voices/{profile_id}/audio")
def get_voice_audio(profile_id: str, session: Session = Depends(get_session)) -> FileResponse:
    profile = voice_profile_service.get_profile(session, profile_id)
    if not profile:
        fail("音色不存在", 404)
    try:
        audio_path = ensure_inside_any(
            Path(profile.reference_audio_path),
            [get_settings().workspace_dir / "voices"],
        )
    except ValueError as exc:
        fail(str(exc))
    if not audio_path.is_file():
        fail("参考音频文件不存在", 404)
    return FileResponse(audio_path)


@router.delete("/voices/{profile_id}")
def delete_voice(profile_id: str, session: Session = Depends(get_session)) -> dict:
    profile = voice_profile_service.get_profile(session, profile_id)
    if not profile:
        fail("音色不存在", 404)
    try:
        voice_profile_service.delete_profile(session, profile)
        return {"success": True, "data": {"id": profile_id}}
    except (OSError, ValueError) as exc:
        logger.exception("Failed to delete voice profile %s", profile_id)
        fail(str(exc))
