import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.database import get_session
from app.infrastructure import process_runner as task_control
from app.services.narration import subtitle_service
from app.services.projects import project_service
from app.services.storyboard import storyboard_service
from app.services.storyboard import scene_workspace_service
from app.services.image_generation import image_generation_service
from app.schemas.storyboard import StoryboardContent
from app.models.storyboard import VisualScene


router = APIRouter(tags=["subtitles"])


class SrtImportRequest(BaseModel):
    content: str


class SceneUpdateRequest(BaseModel):
    narration: str | None = Field(default=None, max_length=20_000)
    storyboard: StoryboardContent | None = None
    status: str | None = None
    locked_text: bool | None = None
    locked_audio: bool | None = None
    locked_visual: bool | None = None


class SceneAssetSelectionRequest(BaseModel):
    variant_id: str = Field(min_length=1)


@router.post("/projects/{project_id}/subtitles/import")
def import_project_srt(
    project_id: str,
    payload: SrtImportRequest,
    session: Session = Depends(get_session),
) -> dict:
    project = _require_project(session, project_id)
    try:
        return {"success": True, "data": subtitle_service.import_srt(session, project, payload.content)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": str(exc)}) from exc


@router.get("/projects/{project_id}/subtitles/cues")
def list_project_subtitle_cues(
    project_id: str,
    session: Session = Depends(get_session),
) -> dict:
    _require_project(session, project_id)
    return {"success": True, "data": subtitle_service.list_subtitle_cues(session, project_id)}


@router.get("/projects/{project_id}/storyboard")
def get_project_storyboard(
    project_id: str,
    session: Session = Depends(get_session),
) -> dict:
    _require_project(session, project_id)
    return {"success": True, "data": {"scenes": storyboard_service.list_scenes(session, project_id)}}


@router.put("/projects/{project_id}/storyboard/scenes/{scene_id}")
def update_project_scene(
    project_id: str,
    scene_id: str,
    payload: SceneUpdateRequest,
    session: Session = Depends(get_session),
) -> dict:
    project = _require_project(session, project_id)
    if not payload.model_fields_set:
        raise HTTPException(status_code=400, detail={"error": "No Scene fields were supplied"})
    try:
        scene = storyboard_service.update_scene(
            session,
            project,
            scene_id,
            narration=payload.narration if "narration" in payload.model_fields_set else None,
            storyboard=payload.storyboard if "storyboard" in payload.model_fields_set else None,
            status=payload.status if "status" in payload.model_fields_set else None,
            locked_text=payload.locked_text if "locked_text" in payload.model_fields_set else None,
            locked_audio=payload.locked_audio if "locked_audio" in payload.model_fields_set else None,
            locked_visual=payload.locked_visual if "locked_visual" in payload.model_fields_set else None,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"error": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
    return {"success": True, "data": scene}


@router.get("/projects/{project_id}/storyboard/scenes/{scene_id}/revisions")
def get_scene_revisions(
    project_id: str,
    scene_id: str,
    session: Session = Depends(get_session),
) -> dict:
    _require_project(session, project_id)
    try:
        revisions = storyboard_service.list_scene_revisions(session, project_id, scene_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"error": str(exc)}) from exc
    return {"success": True, "data": revisions}


@router.post("/projects/{project_id}/storyboard/scenes/{scene_id}/revisions/{revision_id}/restore")
def restore_scene_revision(
    project_id: str,
    scene_id: str,
    revision_id: str,
    session: Session = Depends(get_session),
) -> dict:
    project = _require_project(session, project_id)
    try:
        scene = storyboard_service.restore_scene_revision(
            session, project, scene_id, revision_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"error": str(exc)}) from exc
    return {"success": True, "data": scene}


@router.post("/projects/{project_id}/storyboard/scenes/{scene_id}/regenerate")
def regenerate_project_scene(
    project_id: str,
    scene_id: str,
    session: Session = Depends(get_session),
) -> dict:
    project = _require_project(session, project_id)
    try:
        scene = storyboard_service.regenerate_scene(session, project, scene_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"error": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
    return {"success": True, "data": scene}


@router.get("/projects/{project_id}/storyboard/scenes/{scene_id}/assets")
def get_scene_assets(project_id: str, scene_id: str, session: Session = Depends(get_session)) -> dict:
    project = _require_project(session, project_id)
    try:
        data = scene_workspace_service.scene_assets(session, project, scene_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"error": str(exc)}) from exc
    return {"success": True, "data": data}


@router.put("/projects/{project_id}/storyboard/scenes/{scene_id}/assets/selection")
def select_scene_asset(project_id: str, scene_id: str, payload: SceneAssetSelectionRequest, session: Session = Depends(get_session)) -> dict:
    project = _require_project(session, project_id)
    try:
        data = scene_workspace_service.assign_generated_variant(
            session, project, scene_id, payload.variant_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"error": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
    return {"success": True, "data": data}


@router.delete("/projects/{project_id}/storyboard/scenes/{scene_id}/assets/selection")
def clear_scene_asset(project_id: str, scene_id: str, session: Session = Depends(get_session)) -> dict:
    project = _require_project(session, project_id)
    try:
        data = scene_workspace_service.clear_scene_assignments(session, project, scene_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"error": str(exc)}) from exc
    return {"success": True, "data": data}


@router.post("/projects/{project_id}/storyboard/scenes/{scene_id}/assets/regenerate")
def regenerate_scene_assets(project_id: str, scene_id: str, session: Session = Depends(get_session)) -> dict:
    project = _require_project(session, project_id)
    try:
        with task_control.controlled(project.id, "image_generation"):
            image_generation_service.regenerate_scene_images(
                session,
                project,
                scene_id,
                regeneration_id=uuid.uuid4().hex,
            )
        scene = session.get(VisualScene, scene_id)
        if scene:
            scene_workspace_service.invalidate_scene_outputs(project, scene)
        data = scene_workspace_service.scene_assets(session, project, scene_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
    except RuntimeError as exc:
        if "already has a running" in str(exc):
            raise HTTPException(status_code=409, detail={"error": str(exc)}) from exc
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc
    return {"success": True, "data": data}


def _require_project(session: Session, project_id: str):
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"success": False, "error": "Project not found"})
    return project
