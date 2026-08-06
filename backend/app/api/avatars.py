import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session

from app.database import get_session
from app.integrations.avatar.duix_client import DuixClient
from app.models.avatar import AvatarGenerationTask, AvatarProfile
from app.services.avatar import avatar_service


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/avatars", tags=["avatars"])


def ok(data) -> dict:
    return {"success": True, "data": data}


def fail(message: str, status_code: int = 400) -> None:
    raise HTTPException(status_code=status_code, detail={"success": False, "error": message})


@router.get("/duix/health-check")
def health_check() -> dict:
    return ok(DuixClient().health_check())


@router.get("")
def list_avatar_profiles(session: Session = Depends(get_session)) -> dict:
    return ok([profile.model_dump() for profile in avatar_service.list_profiles(session)])


@router.post("")
def create_avatar_profile(
    name: str = Form(...),
    template_video: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> dict:
    try:
        profile = avatar_service.create_profile(
            session,
            name=name,
            source=template_video.file,
            filename=template_video.filename or "avatar.mp4",
        )
        return ok(profile.model_dump())
    except (OSError, RuntimeError, ValueError) as exc:
        logger.exception("Failed to create avatar profile")
        fail(str(exc))


@router.delete("/{avatar_id}")
def delete_avatar_profile(avatar_id: str, session: Session = Depends(get_session)) -> dict:
    profile = session.get(AvatarProfile, avatar_id)
    if not profile:
        fail("人物形象不存在", 404)
    try:
        avatar_service.delete_profile(session, profile)
        return ok({"deleted": True})
    except (OSError, ValueError) as exc:
        fail(str(exc), 409)


@router.get("/{avatar_id}/video")
def get_avatar_video(avatar_id: str, session: Session = Depends(get_session)) -> FileResponse:
    profile = session.get(AvatarProfile, avatar_id)
    if not profile:
        fail("人物形象不存在", 404)
    path = Path(profile.template_video_path)
    if not path.is_file():
        fail("人物形象视频不存在", 404)
    return FileResponse(path, media_type="video/mp4")


@router.post("/tasks")
def create_avatar_task(
    avatar_profile_id: str = Form(...),
    audio: UploadFile = File(...),
    output_filename: str = Form("avatar-video.mp4"),
    chunk_seconds: int = Form(420),
    context_ms: int = Form(800),
    session: Session = Depends(get_session),
) -> dict:
    try:
        task = avatar_service.enqueue_task(
            session,
            avatar_profile_id=avatar_profile_id,
            source=audio.file,
            filename=audio.filename or "voice.wav",
            output_filename=output_filename,
            chunk_seconds=chunk_seconds,
            context_ms=context_ms,
        )
        data = avatar_service.serialize_task(session, task)
        avatar_service.wake_worker()
        return ok(data)
    except (OSError, RuntimeError, ValueError) as exc:
        logger.exception("Failed to create avatar task")
        fail(str(exc))


@router.get("/tasks/list")
def list_avatar_tasks(
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
) -> dict:
    return ok(avatar_service.list_tasks(session, limit))


@router.get("/tasks/{task_id}")
def get_avatar_task(task_id: str, session: Session = Depends(get_session)) -> dict:
    task = session.get(AvatarGenerationTask, task_id)
    if not task:
        fail("数字人任务不存在", 404)
    return ok(avatar_service.serialize_task(session, task))


@router.post("/tasks/{task_id}/retry")
def retry_avatar_task(task_id: str, session: Session = Depends(get_session)) -> dict:
    task = session.get(AvatarGenerationTask, task_id)
    if not task:
        fail("数字人任务不存在", 404)
    try:
        task = avatar_service.retry_task(session, task)
        data = avatar_service.serialize_task(session, task)
        avatar_service.wake_worker()
        return ok(data)
    except ValueError as exc:
        fail(str(exc), 409)


@router.get("/tasks/{task_id}/output")
def get_avatar_task_output(
    task_id: str,
    download: bool = False,
    session: Session = Depends(get_session),
) -> FileResponse:
    task = session.get(AvatarGenerationTask, task_id)
    if not task or not task.result_path:
        fail("数字人视频尚未生成", 404)
    path = Path(task.result_path)
    if not path.is_file():
        fail("数字人视频文件不存在", 404)
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=path.name if download else None,
        content_disposition_type="attachment" if download else "inline",
    )
