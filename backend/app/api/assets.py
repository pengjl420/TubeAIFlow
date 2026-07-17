from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlmodel import Session

from app.database import get_session
from app.schemas.media import AssetImportRequest, SceneAssignmentRequest
from app.models.media import MediaKeyframe, MediaShot
from app.services.media_library import ingestion_service, retrieval_service
from app.services.projects import project_service


router = APIRouter(tags=["assets"])


@router.get("/assets")
def list_assets(
    limit: int = Query(default=200, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> dict:
    return {"success": True, "data": {"assets": ingestion_service.list_assets(session, limit)}}


@router.post("/assets/import")
def import_assets(
    payload: AssetImportRequest,
    session: Session = Depends(get_session),
) -> dict:
    try:
        data = ingestion_service.import_directory(session, payload.directory)
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": str(exc)},
        ) from exc
    return {"success": True, "data": data}


@router.get("/assets/{media_id}")
def get_asset(media_id: str, session: Session = Depends(get_session)) -> dict:
    try:
        data = ingestion_service.get_asset(session, media_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail={"success": False, "error": str(exc)},
        ) from exc
    return {"success": True, "data": data}


@router.post("/assets/{media_id}/ingest")
def ingest_asset(media_id: str, session: Session = Depends(get_session)) -> dict:
    try:
        data = ingestion_service.ingest_asset(session, media_id)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": str(exc)},
        ) from exc
    return {"success": True, "data": data}


@router.get("/assets/shots/{shot_id}/thumbnail", response_class=FileResponse)
def get_shot_thumbnail(shot_id: str, session: Session = Depends(get_session)) -> FileResponse:
    shot = session.get(MediaShot, shot_id)
    if not shot or not shot.thumbnail_path:
        raise HTTPException(status_code=404, detail="缩略图不存在")
    return _media_response(shot.thumbnail_path)


@router.get("/assets/keyframes/{keyframe_id}", response_class=FileResponse)
def get_keyframe(keyframe_id: str, session: Session = Depends(get_session)) -> FileResponse:
    keyframe = session.get(MediaKeyframe, keyframe_id)
    if not keyframe:
        raise HTTPException(status_code=404, detail="关键帧不存在")
    return _media_response(keyframe.path)


@router.get("/projects/{project_id}/storyboard/scenes/{scene_id}/candidates")
def list_scene_candidates(
    project_id: str,
    scene_id: str,
    session: Session = Depends(get_session),
) -> dict:
    _require_project(session, project_id)
    try:
        candidates = retrieval_service.list_scene_candidates(session, project_id, scene_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail={"success": False, "error": str(exc)},
        ) from exc
    return {"success": True, "data": {"candidates": candidates}}


@router.post("/projects/{project_id}/storyboard/scenes/{scene_id}/search")
def search_scene_candidates(
    project_id: str,
    scene_id: str,
    session: Session = Depends(get_session),
) -> dict:
    project = _require_project(session, project_id)
    try:
        data = retrieval_service.search_scene_candidates(session, project, scene_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": str(exc)},
        ) from exc
    return {"success": True, "data": data}


@router.post("/projects/{project_id}/storyboard/scenes/{scene_id}/assign")
def assign_scene_candidate(
    project_id: str,
    scene_id: str,
    payload: SceneAssignmentRequest,
    session: Session = Depends(get_session),
) -> dict:
    project = _require_project(session, project_id)
    try:
        data = retrieval_service.assign_candidate(session, project, scene_id, payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": str(exc)},
        ) from exc
    return {"success": True, "data": data}


def _require_project(session: Session, project_id: str):
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(
            status_code=404,
            detail={"success": False, "error": "Project not found"},
        )
    return project


def _media_response(value: str) -> FileResponse:
    path = Path(value).resolve()
    if not path.is_file():
        raise HTTPException(status_code=404, detail="预览文件不存在")
    return FileResponse(path, media_type="image/jpeg")
