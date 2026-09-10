from collections.abc import Callable

from sqlmodel import Session, select

from app.infrastructure import process_runner as task_control
from app.infrastructure.ffmpeg import ensure_ffmpeg_available
from app.models.project import Project
from app.models.storyboard import SubtitleCue, VisualScene
from app.services.image_generation import (
    hybrid_assignment_service,
    image_assignment_service,
    image_generation_service,
)
from app.services.projects import project_service
from app.services.quality import qa_service
from app.services.rendering import final_renderer, scene_renderer, visual_track_composer
from app.services.storyboard import storyboard_service
from app.workflows.engine import WorkflowContext, WorkflowGraph, WorkflowStep
from app.domain.states import ResourceClass


StageChanged = Callable[[str], None]
STAGES = {
    "storyboard",
    "image_generation",
    "scene_render",
    "visual_track",
    "final_render",
    "quality_check",
    "completed",
}


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
    if stage not in STAGES:
        raise ValueError(f"Unknown video synthesis stage: {stage}")
    _VIDEO_GRAPH.execute(
        WorkflowContext(session=session, project=project, include_video=True),
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
        image_generation_service.generate_project_images(context.session, context.project)
    image_assignment_service.assign_generated_images(context.session, context.project)
    return "scene_render"


def _scene_render_step(context: WorkflowContext) -> str:
    with task_control.controlled(context.project.id, "scene_render"):
        scene_renderer.render_all_scenes(context.session, context.project)
    return "visual_track"


def _visual_track_step(context: WorkflowContext) -> str:
    with task_control.controlled(context.project.id, "visual_track"):
        visual_track_composer.compose_visual_track(context.session, context.project)
    return "final_render"


def _final_render_step(context: WorkflowContext) -> str:
    with task_control.controlled(context.project.id, "final_render"):
        final_renderer.compose_final_video(context.session, context.project)
    return "quality_check"


def _quality_check_step(context: WorkflowContext) -> str:
    with task_control.controlled(context.project.id, "quality_check"):
        report = qa_service.run_quality_check(context.session, context.project)
    if not report.get("passed"):
        error_count = report.get("summary", {}).get("error_count", 0)
        raise RuntimeError(f"Final video quality check failed with {error_count} errors")
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
        ),
        WorkflowStep(
            "image_generation",
            _image_generation_step,
            resource_class=ResourceClass.GPU,
            depends_on=("storyboard",),
            input_artifacts=("scene_plan",),
            output_artifacts=("scene_assets",),
            cacheable=True,
        ),
        WorkflowStep(
            "scene_render",
            _scene_render_step,
            resource_class=ResourceClass.FFMPEG,
            depends_on=("image_generation",),
            input_artifacts=("scene_assets",),
            output_artifacts=("scene_renders",),
            cacheable=True,
        ),
        WorkflowStep(
            "visual_track",
            _visual_track_step,
            resource_class=ResourceClass.FFMPEG,
            depends_on=("scene_render",),
            input_artifacts=("scene_renders",),
            output_artifacts=("visual_track",),
        ),
        WorkflowStep(
            "final_render",
            _final_render_step,
            resource_class=ResourceClass.FFMPEG,
            depends_on=("visual_track",),
            output_artifacts=("final_video",),
        ),
        WorkflowStep(
            "quality_check",
            _quality_check_step,
            depends_on=("final_render",),
            input_artifacts=("final_video",),
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
    return "scene_render"


def resource_class(stage: str) -> ResourceClass:
    if stage not in _VIDEO_GRAPH.stages:
        raise ValueError(f"Unknown video synthesis stage: {stage}")
    return _VIDEO_GRAPH.resource_class(stage)


def regenerate_storyboard(session: Session, project: Project) -> dict:
    return storyboard_service.generate_storyboard(session, project)


def has_subtitles(session: Session, project_id: str) -> bool:
    return session.exec(
        select(SubtitleCue.id).where(SubtitleCue.project_id == project_id).limit(1)
    ).first() is not None


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

    return session.exec(
        select(SceneAssignment.id).where(SceneAssignment.scene_id == scene_id).limit(1)
    ).first() is not None
