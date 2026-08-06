import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.database import get_session
from app.models.local_video_merge import LocalVideoMergeTask
from app.services.rendering import local_video_merge_queue, local_video_merge_service


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tools/local-video-merge", tags=["local-video-merge"])


class LocalVideoMergeRequest(BaseModel):
    media_dir: str = Field(min_length=1)
    output_dir: str = Field(min_length=1)
    output_filename: str = Field(min_length=1, max_length=200)
    target_duration: float = Field(gt=0, le=86400)


@router.post("/tasks")
def create_merge_task(
    payload: LocalVideoMergeRequest,
    session: Session = Depends(get_session),
) -> dict:
    try:
        task = local_video_merge_queue.enqueue(
            session,
            media_dir=payload.media_dir,
            output_dir=payload.output_dir,
            output_filename=payload.output_filename,
            target_duration=payload.target_duration,
        )
        data = local_video_merge_queue.serialize_task(session, task)
        local_video_merge_queue.wake_worker()
        return {"success": True, "data": data}
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": str(exc)},
        ) from exc


@router.get("/tasks")
def list_merge_tasks(
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
) -> dict:
    return {"success": True, "data": local_video_merge_queue.list_tasks(session, limit)}


@router.get("/tasks/{task_id}")
def get_merge_task(
    task_id: str,
    session: Session = Depends(get_session),
) -> dict:
    task = session.get(LocalVideoMergeTask, task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail={"success": False, "error": "拼接任务不存在"},
        )
    return {"success": True, "data": local_video_merge_queue.serialize_task(session, task)}


@router.post("/compose")
def compose_local_video(payload: LocalVideoMergeRequest) -> dict:
    try:
        result = local_video_merge_service.compose_local_video(
            payload.media_dir,
            payload.output_dir,
            payload.output_filename,
            payload.target_duration,
        )
        return {"success": True, "data": result}
    except (OSError, RuntimeError, ValueError) as exc:
        logger.exception("Local video merge failed")
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": str(exc)},
        ) from exc
