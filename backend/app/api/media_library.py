from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session

from app.database import get_session
from app.services.projects import project_service
from app.services.visual_enrichment import asset_library_service


router = APIRouter(tags=["media-library"])


class LocalCandidateSelectionRequest(BaseModel):
    candidate_id: str


def _project(session: Session, project_id: str):
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"error": "Project not found"})
    return project


@router.post("/projects/{project_id}/assets/scan")
def scan_assets(project_id: str, session: Session = Depends(get_session)) -> dict:
    from app.api.tasks import enqueue_asset_scan_job

    return enqueue_asset_scan_job(project_id, session)


@router.get("/projects/{project_id}/storyboard/scenes/{scene_id}/assets/candidates")
def get_scene_candidates(
    project_id: str,
    scene_id: str,
    refresh: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> dict:
    try:
        data = asset_library_service.scene_candidates(
            session, _project(session, project_id), scene_id, refresh=refresh
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"error": str(exc)}) from exc
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
    return {"success": True, "data": data}


@router.put("/projects/{project_id}/storyboard/scenes/{scene_id}/assets/local-selection")
def select_local_candidate(
    project_id: str,
    scene_id: str,
    payload: LocalCandidateSelectionRequest,
    session: Session = Depends(get_session),
) -> dict:
    try:
        data = asset_library_service.assign_local_candidate(
            session, _project(session, project_id), scene_id, payload.candidate_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"error": str(exc)}) from exc
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
    return {"success": True, "data": data}


@router.get("/projects/{project_id}/assets/file")
def get_local_asset(
    project_id: str,
    path: str,
    session: Session = Depends(get_session),
) -> FileResponse:
    project = _project(session, project_id)
    try:
        root = asset_library_service.project_media_directory(project)
        requested = Path(path).expanduser().resolve()
        requested.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail={"error": "Asset is outside the configured directory"}) from exc
    if not requested.is_file():
        raise HTTPException(status_code=404, detail={"error": "Asset file not found"})
    return FileResponse(requested)
