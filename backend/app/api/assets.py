from pathlib import Path
import re
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session

from app.config import get_settings
from app.infrastructure import process_runner as task_control
from app.database import get_session
from app.schemas.media import (
    AssetBatchDeleteRequest,
    AssetImportRequest,
    AssetUpdateRequest,
    SceneAssignmentRequest,
    SceneAssignmentReorderRequest,
    SceneAssignmentRenderUpdate,
)
from app.models.media import MediaFile, MediaKeyframe, MediaShot
from app.services.media_library import ingestion_service, retrieval_service
from app.services.image_generation import image_generation_service, image_selection_service
from app.services.projects import project_service


router = APIRouter(tags=["assets"])
MAX_UPLOAD_BYTES = 8 * 1024 * 1024 * 1024


@router.get("/assets")
def list_assets(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=200, ge=1, le=1000),
    library_role: str | None = Query(default=None),
    search: str = Query(default="", max_length=200),
    session: Session = Depends(get_session),
) -> dict:
    try:
        data = ingestion_service.list_asset_page(
            session,
            page=page,
            page_size=page_size,
            library_role=library_role,
            search=search,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": str(exc)}) from exc
    return {
        "success": True,
        "data": {
            **data,
            "vector_model": ingestion_service.current_vector_model(),
        },
    }


@router.post("/assets/import")
def import_assets(
    payload: AssetImportRequest,
    session: Session = Depends(get_session),
) -> dict:
    try:
        data = ingestion_service.import_directory(
            session,
            payload.directory,
            payload.library_role,
            payload.fallback_category,
            payload.mood,
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": str(exc)},
        ) from exc
    return {"success": True, "data": data}


@router.patch("/assets/{media_id}")
def update_asset(
    media_id: str,
    payload: AssetUpdateRequest,
    session: Session = Depends(get_session),
) -> dict:
    try:
        data = ingestion_service.update_asset(session, media_id, payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": str(exc)},
        ) from exc
    return {"success": True, "data": data}


@router.delete("/assets/batch")
def delete_assets(
    payload: AssetBatchDeleteRequest,
    session: Session = Depends(get_session),
) -> dict:
    try:
        data = ingestion_service.delete_assets(session, payload.media_ids)
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": f"删除素材预览文件失败：{exc}"},
        ) from exc
    return {"success": True, "data": data}


@router.delete("/assets/{media_id}")
def delete_asset(media_id: str, session: Session = Depends(get_session)) -> dict:
    if not session.get(MediaFile, media_id):
        raise HTTPException(
            status_code=404,
            detail={"success": False, "error": "素材不存在"},
        )
    try:
        data = ingestion_service.delete_assets(session, [media_id])
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": f"删除素材预览文件失败：{exc}"},
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


@router.get("/projects/{project_id}/storyboard/assignments/coverage")
def list_project_assignment_coverage(
    project_id: str,
    session: Session = Depends(get_session),
) -> dict:
    _require_project(session, project_id)
    data = retrieval_service.list_project_assignment_coverage(session, project_id)
    return {"success": True, "data": data}


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


@router.post("/projects/{project_id}/storyboard/scenes/{scene_id}/generate-images")
def generate_scene_images(
    project_id: str,
    scene_id: str,
    session: Session = Depends(get_session),
) -> dict:
    project = _require_project(session, project_id)
    if project_service.get_project_video_mode(project) != project_service.VIDEO_MODE_AI_GENERATED_IMAGES:
        raise HTTPException(
            status_code=409,
            detail={"success": False, "error": "当前项目未启用本地图片生成模式"},
        )
    try:
        with task_control.controlled(project.id, "image_generation"):
            data = image_generation_service.generate_scene_images(session, project, scene_id)
        data["selection"] = image_selection_service.score_scene_images(
            session, project, scene_id
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": str(exc)},
        ) from exc
    data["candidates"] = retrieval_service.list_scene_candidates(
        session, project_id, scene_id
    )
    return {"success": True, "data": data}


@router.get("/projects/{project_id}/storyboard/scenes/{scene_id}/generated-images")
def list_generated_scene_images(
    project_id: str,
    scene_id: str,
    session: Session = Depends(get_session),
) -> dict:
    _require_project(session, project_id)
    return {
        "success": True,
        "data": {
            "variants": image_generation_service.list_scene_variants(
                session, project_id, scene_id
            )
        },
    }


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


@router.get("/projects/{project_id}/storyboard/scenes/{scene_id}/assignments")
def list_scene_assignments(
    project_id: str,
    scene_id: str,
    session: Session = Depends(get_session),
) -> dict:
    _require_project(session, project_id)
    try:
        data = retrieval_service.list_scene_assignments(session, project_id, scene_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"success": False, "error": str(exc)}) from exc
    return {"success": True, "data": data}


@router.delete("/projects/{project_id}/storyboard/scenes/{scene_id}/assignments/{assignment_id}")
def delete_scene_assignment(
    project_id: str,
    scene_id: str,
    assignment_id: str,
    session: Session = Depends(get_session),
) -> dict:
    _require_project(session, project_id)
    try:
        data = retrieval_service.delete_scene_assignment(
            session, project_id, scene_id, assignment_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": str(exc)}) from exc
    return {"success": True, "data": data}


@router.put("/projects/{project_id}/storyboard/scenes/{scene_id}/assignments/order")
def reorder_scene_assignments(
    project_id: str,
    scene_id: str,
    payload: SceneAssignmentReorderRequest,
    session: Session = Depends(get_session),
) -> dict:
    _require_project(session, project_id)
    try:
        data = retrieval_service.reorder_scene_assignments(
            session, project_id, scene_id, payload.assignment_ids
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": str(exc)}) from exc
    return {"success": True, "data": data}


@router.patch("/projects/{project_id}/storyboard/scenes/{scene_id}/assignments/{assignment_id}/render")
def update_scene_assignment_render(
    project_id: str,
    scene_id: str,
    assignment_id: str,
    payload: SceneAssignmentRenderUpdate,
    session: Session = Depends(get_session),
) -> dict:
    _require_project(session, project_id)
    try:
        data = retrieval_service.update_scene_assignment_render(
            session,
            project_id,
            scene_id,
            assignment_id,
            payload.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": str(exc)}) from exc
    return {"success": True, "data": data}


@router.post("/projects/{project_id}/storyboard/scenes/{scene_id}/assignments/confirm-fallback")
def confirm_scene_fallback_assignments(
    project_id: str,
    scene_id: str,
    session: Session = Depends(get_session),
) -> dict:
    _require_project(session, project_id)
    try:
        data = retrieval_service.confirm_scene_fallback_assignments(
            session, project_id, scene_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": str(exc)}) from exc
    return {"success": True, "data": data}


@router.post("/projects/{project_id}/storyboard/scenes/{scene_id}/upload")
def upload_scene_asset(
    project_id: str,
    scene_id: str,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> dict:
    project = _require_project(session, project_id)
    original_name = Path(file.filename or "upload").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in ingestion_service.VIDEO_EXTENSIONS | ingestion_service.IMAGE_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": "不支持该素材格式，请上传常见视频或图片文件"},
        )

    safe_name = re.sub(r'[^\w\-.\u4e00-\u9fff]+', "_", original_name).strip("._")
    safe_name = safe_name or f"upload{suffix}"
    upload_dir = get_settings().workspace_dir / "assets" / "uploads" / uuid4().hex
    upload_dir.mkdir(parents=True, exist_ok=False)
    destination = upload_dir / safe_name
    imported = False
    try:
        size = 0
        with destination.open("wb") as target:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise ValueError("上传素材不能超过 8 GB")
                target.write(chunk)
        media_file, imported = ingestion_service.import_uploaded_asset(session, destination)
        if not imported:
            destination.unlink(missing_ok=True)
            upload_dir.rmdir()
        ingestion = ingestion_service.ingest_asset(session, media_file.id)
        candidates = retrieval_service.register_manual_asset_candidates(
            session, project, scene_id, media_file.id
        )
    except (OSError, RuntimeError, ValueError) as exc:
        if not imported:
            destination.unlink(missing_ok=True)
            if upload_dir.exists() and not any(upload_dir.iterdir()):
                upload_dir.rmdir()
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": str(exc)},
        ) from exc
    finally:
        file.file.close()
    return {
        "success": True,
        "data": {
            "asset": ingestion["asset"],
            "candidates": candidates,
            "ingestion_errors": ingestion["errors"],
        },
    }


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
    media_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return FileResponse(path, media_type=media_type)
