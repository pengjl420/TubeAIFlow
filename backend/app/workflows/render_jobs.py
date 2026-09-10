from sqlmodel import Session, select

from app.infrastructure.serialization import dump_json, load_json_object
from app.models.project import Project
from app.models.task import TaskRun
from app.services.rendering import (
    final_renderer,
    preview_renderer,
    rough_cut_service,
    scene_renderer,
    visual_track_composer,
)
from app.shared.time import utc_now_iso
from app.workflows.engine import StageChanged


TIMELINE_PREVIEW_WORKFLOW_ID = "timeline_preview_render"
FINAL_RENDER_WORKFLOW_ID = "final_render"
VISUAL_TRACK_WORKFLOW_ID = "visual_track_render"
ROUGH_CUT_WORKFLOW_ID = "rough_cut_render"


def run_timeline_preview_job(
    session: Session,
    project: Project,
    current_stage: str,
    _include_video: bool,
    on_stage_changed: StageChanged,
) -> None:
    if current_stage != "render":
        raise ValueError(f"Unknown Timeline preview Job stage: {current_stage}")
    task = _running_task(session, project.id, TIMELINE_PREVIEW_WORKFLOW_ID)
    request = load_json_object(task.request_json)
    _set_progress(session, task, 10)
    result = preview_renderer.render_timeline_preview(
        session,
        project,
        start_ms=int(request.get("start_ms", 0)),
        duration_ms=int(request.get("duration_ms", 30_000)),
    )
    _finish(session, task, result)
    on_stage_changed("completed")


def run_final_render_job(
    session: Session,
    project: Project,
    current_stage: str,
    _include_video: bool,
    on_stage_changed: StageChanged,
) -> None:
    if current_stage not in {"scene_render", "visual_track", "final_render"}:
        raise ValueError(f"Unknown Final Render Job stage: {current_stage}")
    task = _running_task(session, project.id, FINAL_RENDER_WORKFLOW_ID)
    if current_stage == "scene_render":
        _set_progress(session, task, 10)
        scene_renderer.render_all_scenes(session, project)
        _set_progress(session, task, 40)
        on_stage_changed("visual_track")
        current_stage = "visual_track"
    if current_stage == "visual_track":
        _set_progress(session, task, 45)
        visual_track_composer.compose_visual_track(session, project)
        _set_progress(session, task, 70)
        on_stage_changed("final_render")
    result = final_renderer.compose_final_video(session, project)
    _finish(session, task, result)
    on_stage_changed("completed")


def run_visual_track_job(
    session: Session,
    project: Project,
    current_stage: str,
    _include_video: bool,
    on_stage_changed: StageChanged,
) -> None:
    if current_stage != "render":
        raise ValueError(f"Unknown Visual Track Job stage: {current_stage}")
    task = _running_task(session, project.id, VISUAL_TRACK_WORKFLOW_ID)
    _set_progress(session, task, 10)
    result = visual_track_composer.compose_visual_track(session, project)
    _finish(session, task, result)
    on_stage_changed("completed")


def run_rough_cut_job(
    session: Session,
    project: Project,
    current_stage: str,
    _include_video: bool,
    on_stage_changed: StageChanged,
) -> None:
    if current_stage != "render":
        raise ValueError(f"Unknown Rough Cut Job stage: {current_stage}")
    task = _running_task(session, project.id, ROUGH_CUT_WORKFLOW_ID)
    _set_progress(session, task, 10)
    path = rough_cut_service.compose_video(session, project)
    _finish(session, task, {"path": str(path)})
    on_stage_changed("completed")


def _running_task(session: Session, project_id: str, workflow: str) -> TaskRun:
    task = session.exec(
        select(TaskRun).where(
            TaskRun.project_id == project_id,
            TaskRun.workflow == workflow,
            TaskRun.status == "running",
        )
    ).first()
    if not task:
        raise RuntimeError("Running Job record not found")
    return task


def _set_progress(session: Session, task: TaskRun, progress: float) -> None:
    task.progress = progress
    task.updated_at = utc_now_iso()
    session.add(task)
    session.commit()


def _finish(session: Session, task: TaskRun, result: dict) -> None:
    task.result_json = dump_json(result)
    task.progress = 100
    task.updated_at = utc_now_iso()
    session.add(task)
    session.commit()
