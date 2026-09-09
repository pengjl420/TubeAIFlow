import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session
from sqlmodel import select

from app.config import get_settings
from app.database import get_session
from app.infrastructure import process_runner as task_control
from app.infrastructure.project_layout import (
    get_final_fcpxml_path,
    get_final_video_path,
    get_project_work_dir,
)
from app.models.media import SceneAssignment
from app.models.storyboard import VisualScene
from app.services.projects import project_service
from app.services.quality import qa_service
from app.services.rendering import (
    final_renderer,
    rough_cut_service,
    scene_renderer,
    timeline_composer,
    timeline_editor_service,
    visual_track_composer,
)


router = APIRouter(tags=["videos"])


class VideoSettingsRequest(BaseModel):
    media_video_dir: str


class TimelineClipUpdateRequest(BaseModel):
    sequence_index: int | None = None
    display_duration_ms: int | None = None
    trim_start_ms: int | None = None
    trim_end_ms: int | None = None
    playback_speed: float | None = None
    motion_type: str | None = None
    zoom_start: float | None = None
    zoom_end: float | None = None
    pan_direction: str | None = None
    crop_anchor: str | None = None
    transition: str | None = None


@router.get("/projects/{project_id}/timeline/editor")
def get_timeline_editor(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = _require_project(session, project_id)
    return {"success": True, "data": timeline_editor_service.timeline(session, project)}


@router.put("/projects/{project_id}/timeline/clips/{clip_id}")
def update_timeline_clip(
    project_id: str,
    clip_id: str,
    payload: TimelineClipUpdateRequest,
    session: Session = Depends(get_session),
) -> dict:
    project = _require_project(session, project_id)
    try:
        data = timeline_editor_service.update_visual_clip(
            session, project, clip_id, payload.model_dump(exclude_unset=True)
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"error": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
    return {"success": True, "data": data}


@router.post("/projects/{project_id}/video/settings")
def save_video_settings(
    project_id: str,
    payload: VideoSettingsRequest,
    session: Session = Depends(get_session),
) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(
            status_code=404, detail={"success": False, "error": "Project not found"}
        )
    try:
        return {
            "success": True,
            "data": rough_cut_service.save_video_settings(
                session, project, payload.media_video_dir
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": str(exc)}) from exc


@router.post("/projects/{project_id}/video/compose")
def compose_video(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(
            status_code=404, detail={"success": False, "error": "Project not found"}
        )
    try:
        project = project_service.ensure_output_filename(session, project)
        with task_control.controlled(project_id, "video"):
            path = rough_cut_service.compose_video(session, project)
        return {"success": True, "data": {"path": str(path)}}
    except rough_cut_service.VideoCompositionRunningError as exc:
        raise HTTPException(status_code=409, detail={"success": False, "error": str(exc)}) from exc
    except task_control.TaskCancelledError as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": str(exc)}) from exc
    except (ValueError, RuntimeError, OSError) as exc:
        try:
            rough_cut_service.mark_video_progress_failed(project, str(exc))
        except OSError:
            # Preserve the original composition error if the progress file is
            # itself temporarily unavailable.
            pass
        raise HTTPException(status_code=400, detail={"success": False, "error": str(exc)}) from exc


@router.get("/projects/{project_id}/video/status")
def video_status(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(
            status_code=404, detail={"success": False, "error": "Project not found"}
        )
    return {"success": True, "data": rough_cut_service.read_video_progress(project)}


@router.post("/projects/{project_id}/render/scenes/{scene_id}")
def render_scene(project_id: str, scene_id: str, session: Session = Depends(get_session)) -> dict:
    project = _require_project(session, project_id)
    scene = session.get(VisualScene, scene_id)
    if not scene or scene.project_id != project_id:
        raise HTTPException(status_code=404, detail={"success": False, "error": "视觉场景不存在"})
    try:
        data = scene_renderer.render_scene(session, project, scene)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": str(exc)}) from exc
    return {"success": True, "data": data}


@router.post("/projects/{project_id}/render/final")
def render_final(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = _require_project(session, project_id)
    try:
        visual_track_composer.compose_visual_track(session, project)
        data = final_renderer.compose_final_video(session, project)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": str(exc)}) from exc
    return {"success": True, "data": data}


@router.post("/projects/{project_id}/render/visual-track")
def render_visual_track(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = _require_project(session, project_id)
    try:
        data = visual_track_composer.compose_visual_track(session, project)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": str(exc)}) from exc
    return {"success": True, "data": data}


@router.get("/projects/{project_id}/render/status")
def intelligent_render_status(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = _require_project(session, project_id)
    scenes = list(
        session.exec(
            select(VisualScene)
            .where(VisualScene.project_id == project_id)
            .order_by(VisualScene.scene_index)
        ).all()
    )
    scene_ids = {scene.id for scene in scenes}
    assignments = list(
        session.exec(select(SceneAssignment).where(SceneAssignment.project_id == project_id)).all()
    )
    assignments = [item for item in assignments if item.scene_id in scene_ids]
    scene_coverages = [timeline_composer.scene_coverage(session, scene) for scene in scenes]
    completed_scene_count = sum(coverage["complete"] for coverage in scene_coverages)
    rendered = sum(scene_renderer.scene_output_path(project, scene).is_file() for scene in scenes)
    work_dir = get_project_work_dir(project, get_settings().workspace_dir)
    intelligent_render_complete = (work_dir / "reports" / "render_report.json").is_file()
    visual_track_path = work_dir / "renders" / "visual_track.mp4"
    scene_manifest_path = work_dir / "renders" / "scenes" / "manifest.json"
    scene_manifest = {}
    if scene_manifest_path.is_file():
        try:
            scene_manifest = json.loads(scene_manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            scene_manifest = {}
    final_video_path = get_final_video_path(project, get_settings().workspace_dir)
    final_fcpxml_path = get_final_fcpxml_path(project, get_settings().workspace_dir)
    return {
        "success": True,
        "data": {
            "scene_count": len(scenes),
            "assignment_count": completed_scene_count,
            "shot_assignment_count": len(assignments),
            "rendered_scene_count": rendered,
            "scene_render_results": scene_manifest,
            "visual_track_path": str(visual_track_path),
            "visual_track_exists": visual_track_path.is_file(),
            "final_video_path": str(final_video_path),
            "final_video_exists": final_video_path.is_file() and intelligent_render_complete,
            "final_fcpxml_path": str(final_fcpxml_path),
            "final_fcpxml_exists": final_fcpxml_path.is_file(),
            "qa_report": qa_service.read_report(project),
            "work_dir": str(work_dir),
        },
    }


def _require_project(session: Session, project_id: str):
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(
            status_code=404, detail={"success": False, "error": "Project not found"}
        )
    return project
