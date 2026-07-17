from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.database import get_session
from app.schemas.media import AssetImportRequest, SceneAssignmentRequest
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
