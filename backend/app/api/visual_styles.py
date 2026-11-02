from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.database import get_session
from app.services.projects import project_service
from app.services.visual_styles import style_asset_service, style_service, style_test_queue


router = APIRouter(prefix="/visual-styles", tags=["visual-styles"])


def ok(data) -> dict:
    return {"success": True, "data": data}


def fail(message: str, status_code: int = 400) -> None:
    raise HTTPException(status_code=status_code, detail={"success": False, "error": message})


class CreateStyleRequest(BaseModel):
    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    style_prompt: str
    negative_prompt: str = ""


class UpdateStyleRequest(CreateStyleRequest):
    continuity_rules: list[str] = Field(default_factory=list)
    composition_rules: list[str] = Field(default_factory=list)
    motion_preset: dict = Field(default_factory=dict)
    source: str = "manual"


class OptimizeStyleRequest(BaseModel):
    style_prompt: str
    negative_prompt: str = ""
    goal: str = "加强全片风格一致性并优化为 Seedream 适用格式"


class TestStyleRequest(BaseModel):
    client_request_id: str = Field(min_length=1, max_length=64)
    revision_id: str | None = None
    scene_description: str
    candidates: int = Field(default=1, ge=1, le=4)


class BindProjectStyleRequest(BaseModel):
    revision_id: str
    apply_existing: bool = False


class UpdateStyleAssetStatusRequest(BaseModel):
    status: Literal["approved", "rejected", "archived"]


@router.get("")
def list_styles(include_archived: bool = False, session: Session = Depends(get_session)) -> dict:
    return ok(style_service.list_profiles(session, include_archived=include_archived))


@router.post("")
def create_style(payload: CreateStyleRequest, session: Session = Depends(get_session)) -> dict:
    try:
        return ok(style_service.create_profile(session, **payload.model_dump()))
    except ValueError as exc:
        fail(str(exc))


@router.get("/{style_id}")
def get_style(style_id: str, session: Session = Depends(get_session)) -> dict:
    try:
        return ok(style_service.serialize_profile(session, style_service.get_profile(session, style_id)))
    except LookupError as exc:
        fail(str(exc), 404)


@router.put("/{style_id}/draft")
def update_style_draft(
    style_id: str, payload: UpdateStyleRequest, session: Session = Depends(get_session)
) -> dict:
    try:
        profile = style_service.get_profile(session, style_id)
        return ok(style_service.update_draft(session, profile, **payload.model_dump()))
    except LookupError as exc:
        fail(str(exc), 404)
    except ValueError as exc:
        fail(str(exc))


@router.post("/{style_id}/publish")
def publish_style(style_id: str, session: Session = Depends(get_session)) -> dict:
    try:
        return ok(style_service.publish_draft(session, style_service.get_profile(session, style_id)))
    except LookupError as exc:
        fail(str(exc), 404)
    except ValueError as exc:
        fail(str(exc))


@router.post("/{style_id}/duplicate")
def duplicate_style(style_id: str, session: Session = Depends(get_session)) -> dict:
    try:
        return ok(style_service.duplicate_profile(session, style_service.get_profile(session, style_id)))
    except LookupError as exc:
        fail(str(exc), 404)
    except ValueError as exc:
        fail(str(exc))


@router.post("/{style_id}/archive")
def archive_style(style_id: str, session: Session = Depends(get_session)) -> dict:
    try:
        return ok(style_service.archive_profile(session, style_service.get_profile(session, style_id)))
    except LookupError as exc:
        fail(str(exc), 404)
    except ValueError as exc:
        fail(str(exc))


@router.post("/{style_id}/optimize")
def optimize_style(
    style_id: str, payload: OptimizeStyleRequest, session: Session = Depends(get_session)
) -> dict:
    try:
        style_service.get_profile(session, style_id)
        return ok(style_service.optimize_prompt(**payload.model_dump()))
    except LookupError as exc:
        fail(str(exc), 404)
    except (ValueError, RuntimeError) as exc:
        fail(str(exc))


@router.post("/{style_id}/tests", status_code=202)
def test_style(
    style_id: str, payload: TestStyleRequest, session: Session = Depends(get_session)
) -> dict:
    try:
        profile = style_service.get_profile(session, style_id)
        revision_id = payload.revision_id or profile.draft_revision_id or profile.current_revision_id
        if not revision_id:
            raise ValueError("风格没有可测试的版本")
        revision = style_service.get_revision(session, revision_id)
        if revision.style_profile_id != profile.id:
            raise ValueError("测试版本不属于当前风格")
        result = style_service.enqueue_style_test(
            session,
            revision,
            scene_description=payload.scene_description,
            candidates=payload.candidates,
            client_request_id=payload.client_request_id,
        )
        style_test_queue.wake_worker()
        return ok(result)
    except LookupError as exc:
        fail(str(exc), 404)
    except (ValueError, RuntimeError, OSError) as exc:
        fail(str(exc))


@router.get("/{style_id}/tests")
def list_style_tests(style_id: str, session: Session = Depends(get_session)) -> dict:
    try:
        style_service.get_profile(session, style_id)
        return ok(style_service.list_test_runs(session, style_id))
    except LookupError as exc:
        fail(str(exc), 404)


@router.get("/{style_id}/assets")
def list_style_assets(style_id: str, session: Session = Depends(get_session)) -> dict:
    try:
        style_service.get_profile(session, style_id)
        return ok(style_asset_service.list_assets(session, style_id))
    except LookupError as exc:
        fail(str(exc), 404)


@router.get("/{style_id}/assets/{asset_id}/image")
def get_style_asset_image(
    style_id: str, asset_id: str, session: Session = Depends(get_session)
) -> FileResponse:
    try:
        path = style_asset_service.asset_image_path(session, style_id, asset_id)
        if not path.is_file():
            fail("风格资产文件不存在", 404)
        return FileResponse(path, filename=path.name)
    except LookupError as exc:
        fail(str(exc), 404)
    except ValueError as exc:
        fail(str(exc))


@router.put("/{style_id}/assets/{asset_id}")
def update_style_asset(
    style_id: str,
    asset_id: str,
    payload: UpdateStyleAssetStatusRequest,
    session: Session = Depends(get_session),
) -> dict:
    try:
        return ok(style_asset_service.set_asset_status(session, style_id, asset_id, payload.status))
    except LookupError as exc:
        fail(str(exc), 404)
    except ValueError as exc:
        fail(str(exc))


@router.get("/tests/{run_id}")
def get_style_test(run_id: str, session: Session = Depends(get_session)) -> dict:
    try:
        return ok(style_service.get_test_run(session, run_id))
    except LookupError as exc:
        fail(str(exc), 404)


@router.get("/tests/{run_id}/images/{index}")
def get_test_image(run_id: str, index: int, session: Session = Depends(get_session)) -> FileResponse:
    try:
        path = style_service.test_image_path(session, run_id, index)
        if not path.is_file():
            fail("测试图片文件不存在", 404)
        return FileResponse(path, media_type="image/png", filename=path.name)
    except LookupError as exc:
        fail(str(exc), 404)
    except ValueError as exc:
        fail(str(exc))


@router.put("/projects/{project_id}")
def bind_project_style(
    project_id: str,
    payload: BindProjectStyleRequest,
    session: Session = Depends(get_session),
) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        fail("项目不存在", 404)
    try:
        revision = style_service.get_revision(session, payload.revision_id)
        if revision.status != "published":
            raise ValueError("项目只能绑定已发布的风格版本")
        updated = project_service.update_project_visual_style(
            session, project, revision, apply_existing=payload.apply_existing
        )
        return ok(project_service.get_project_response(session, updated))
    except LookupError as exc:
        fail(str(exc), 404)
    except ValueError as exc:
        fail(str(exc))
