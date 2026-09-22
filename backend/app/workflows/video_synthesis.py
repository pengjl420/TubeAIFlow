from collections.abc import Callable

from sqlmodel import Session, select

from app.infrastructure import process_runner as task_control
from app.infrastructure.ffmpeg import ensure_ffmpeg_available
from app.config import get_settings
from app.infrastructure.project_layout import get_final_prproj_path
from app.models.project import Project
from app.models.storyboard import SubtitleCue, VisualScene
from app.services.image_generation import (
    hybrid_assignment_service,
    image_assignment_service,
    image_generation_service,
)
from app.services.projects import project_service
from app.services.projects import prproj_export_service
from app.services.storyboard import storyboard_service
from app.services.visual_enrichment import project_workflow as advanced_visual_workflow
from app.workflows.engine import WorkflowContext, WorkflowGraph, WorkflowStep
from app.domain.states import ResourceClass


StageChanged = Callable[[str], None]
STAGES = {
    "storyboard",
    "image_generation",
    "project_export",
    "delivery_quality_check",
    "completed",
}
LEGACY_RENDER_STAGES = {"scene_render", "visual_track", "final_render", "quality_check"}


def run_video_synthesis(
    session: Session,
    project: Project,
    current_stage: str,
    on_stage_changed: StageChanged,
) -> None:
    video_mode = project_service.get_project_video_mode(project)
    if video_mode not in {
        project_service.VIDEO_MODE_AI_GENERATED_IMAGES,
        project_service.VIDEO_MODE_AI_LANDSCAPE_MIX,
    }:
        raise ValueError("Video synthesis only supports AI storyboard and mixed video modes")
    ensure_ffmpeg_available()

    stage = current_stage or "storyboard"
    if stage in LEGACY_RENDER_STAGES:
        stage = "project_export"
    if stage not in STAGES:
        raise ValueError(f"Unknown video synthesis stage: {stage}")
    _VIDEO_GRAPH.execute(
        WorkflowContext(
            session=session,
            project=project,
            include_video=True,
            artifact_exists=lambda name: _artifact_exists(session, project, name),
        ),
        stage,
        on_stage_changed,
    )


def _storyboard_step(context: WorkflowContext) -> str:
    with task_control.controlled(context.project.id, "storyboard"):
        regenerate_storyboard(context.session, context.project)
    return "image_generation"


def _image_generation_step(context: WorkflowContext) -> str:
    video_mode = project_service.get_project_video_mode(context.project)
    if video_mode == project_service.VIDEO_MODE_AI_LANDSCAPE_MIX:
        hybrid_assignment_service.assign_landscape_scenes(context.session, context.project)
    with task_control.controlled(context.project.id, "image_generation"):
        advanced_visual_workflow.enrich_project_visuals(context.session, context.project)
        image_generation_service.generate_project_images(context.session, context.project)
    image_assignment_service.assign_generated_images(context.session, context.project)
    return "project_export"


def _project_export_step(context: WorkflowContext) -> str:
    with task_control.controlled(context.project.id, "project_export"):
        prproj_export_service.export_project_prproj(context.session, context.project)
    return "delivery_quality_check"


def _delivery_quality_check_step(context: WorkflowContext) -> str:
    from app.services.quality import qa_service

    with task_control.controlled(context.project.id, "delivery_quality_check"):
        qa_service.run_quality_check(context.session, context.project)
    return "completed"


_VIDEO_GRAPH = WorkflowGraph(
    (
        WorkflowStep(
            "storyboard",
            _storyboard_step,
            resource_class=ResourceClass.API,
            input_artifacts=("subtitle_timeline",),
            output_artifacts=("scene_plan",),
            cacheable=True,
            cached_next_stage="image_generation",
        ),
        WorkflowStep(
            "image_generation",
            _image_generation_step,
            resource_class=ResourceClass.GPU,
            depends_on=("storyboard",),
            input_artifacts=("scene_plan",),
            output_artifacts=("scene_assets",),
        ),
        WorkflowStep(
            "project_export",
            _project_export_step,
            resource_class=ResourceClass.CPU,
            depends_on=("image_generation",),
            input_artifacts=("scene_assets",),
            output_artifacts=("prproj",),
        ),
        WorkflowStep(
            "delivery_quality_check",
            _delivery_quality_check_step,
            resource_class=ResourceClass.FFMPEG,
            depends_on=("project_export",),
            input_artifacts=("prproj",),
            output_artifacts=("quality_report",),
        ),
    )
)


def initial_stage(session: Session, project_id: str) -> str:
    project = session.get(Project, project_id)
    if not project:
        raise ValueError("Project not found")
    scenes = _scenes(session, project_id)
    if not scenes:
        return "storyboard"
    if any(not scene.storyboard_json for scene in scenes):
        return "storyboard"
    if any(not _scene_has_assignment(session, scene.id) for scene in scenes):
        return "image_generation"
    prproj_path = get_final_prproj_path(project, get_settings().workspace_dir)
    if prproj_path.is_file() and prproj_path.stat().st_size > 0:
        return "delivery_quality_check"
    return "project_export"


def resource_class(stage: str) -> ResourceClass:
    if stage not in _VIDEO_GRAPH.stages:
        raise ValueError(f"Unknown video synthesis stage: {stage}")
    return _VIDEO_GRAPH.resource_class(stage)


def regenerate_storyboard(session: Session, project: Project) -> dict:
    return storyboard_service.generate_storyboard(session, project)


def has_subtitles(session: Session, project_id: str) -> bool:
    return (
        session.exec(
            select(SubtitleCue.id).where(SubtitleCue.project_id == project_id).limit(1)
        ).first()
        is not None
    )


def _scenes(session: Session, project_id: str) -> list[VisualScene]:
    return list(
        session.exec(
            select(VisualScene)
            .where(VisualScene.project_id == project_id)
            .order_by(VisualScene.scene_index)
        ).all()
    )


def _scene_has_assignment(session: Session, scene_id: str) -> bool:
    from app.models.media import SceneAssignment

    return (
        session.exec(
            select(SceneAssignment.id).where(SceneAssignment.scene_id == scene_id).limit(1)
        ).first()
        is not None
    )


def _artifact_exists(session: Session, project: Project, name: str) -> bool:
    settings = get_settings()
    scenes = _scenes(session, project.id)
    if name == "subtitle_timeline":
        return has_subtitles(session, project.id)
    if name == "scene_plan":
        return bool(scenes) and all(bool(scene.storyboard_json) for scene in scenes)
    if name == "scene_assets":
        return bool(scenes) and all(_scene_has_assignment(session, scene.id) for scene in scenes)
    if name == "prproj":
        path = get_final_prproj_path(project, settings.workspace_dir)
        return path.is_file() and path.stat().st_size > 0
    if name == "quality_report":
        from app.services.quality import qa_service

        return qa_service.read_report(project, session) is not None
    return False
