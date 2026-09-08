from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.config import Settings
from app.database import get_session
from app.services.settings import system_settings_service
from app.services.projects import native_dialog_service


router = APIRouter(tags=["settings"])


@router.get("/settings/cleanup/status")
def get_cleanup_status() -> dict:
    from app.services.settings import cleanup_service

    return {"success": True, "data": cleanup_service.get_status()}


class SystemSettingsUpdate(Settings):
    pass


class ClearSecretRequest(BaseModel):
    field: str


class DirectoryPickerRequest(BaseModel):
    initial_path: str | None = None
    title: str = "选择文件夹"


@router.post("/tools/select-directory")
def select_directory(payload: DirectoryPickerRequest) -> dict:
    try:
        selected = native_dialog_service.select_directory(payload.initial_path, payload.title)
        return {"success": True, "data": {"path": selected}}
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail={"success": False, "error": str(exc)}) from exc


@router.get("/settings")
def get_system_settings() -> dict:
    return {"success": True, "data": system_settings_service.get_public_settings()}


@router.put("/settings")
def update_system_settings(
    payload: SystemSettingsUpdate,
    session: Session = Depends(get_session),
) -> dict:
    try:
        data = system_settings_service.save_settings(session, payload.model_dump(mode="json"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": str(exc)}) from exc
    return {"success": True, "data": data}


@router.post("/settings/clear-secret")
def clear_secret(payload: ClearSecretRequest, session: Session = Depends(get_session)) -> dict:
    try:
        data = system_settings_service.clear_secret(session, payload.field)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": str(exc)}) from exc
    return {"success": True, "data": data}


@router.get("/settings/ffmpeg/status")
def get_ffmpeg_status() -> dict:
    return {"success": True, "data": system_settings_service.get_ffmpeg_status()}


@router.get("/settings/premiere/status")
def get_premiere_status() -> dict:
    return {"success": True, "data": system_settings_service.get_premiere_status()}


@router.post("/settings/ffmpeg/install")
def install_ffmpeg(session: Session = Depends(get_session)) -> dict:
    try:
        data = system_settings_service.install_ffmpeg(session)
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": str(exc)}) from exc
    return {"success": True, "data": data}
