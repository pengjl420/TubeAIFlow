import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.rendering import local_video_merge_service


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tools/local-video-merge", tags=["local-video-merge"])


class LocalVideoMergeRequest(BaseModel):
    media_dir: str = Field(min_length=1)
    output_dir: str = Field(min_length=1)
    output_filename: str = Field(min_length=1, max_length=200)
    target_duration: float = Field(gt=0, le=86400)


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
