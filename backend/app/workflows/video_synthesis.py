from collections.abc import Callable

from sqlmodel import Session, select

from app.infrastructure import process_runner as task_control
from app.infrastructure.ffmpeg import ensure_ffmpeg_available
from app.models.project import Project
from app.models.storyboard import SubtitleCue, VisualScene
from app.services.image_generation import image_assignment_service, image_generation_service
from app.services.projects import project_service
from app.services.quality import qa_service
from app.services.rendering import final_renderer, scene_renderer, visual_track_composer
from app.services.storyboard import storyboard_service


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
    if project_service.get_project_video_mode(project) != project_service.VIDEO_MODE_AI_GENERATED_IMAGES:
        raise ValueError("Video synthesis only supports project-generated images")
    ensure_ffmpeg_available()

    stage = current_stage or "storyboard"
    if stage not in STAGES:
        raise ValueError(f"Unknown video synthesis stage: {stage}")

    if stage == "storyboard":
        with task_control.controlled(project.id, "storyboard"):
            regenerate_storyboard(session, project)
        stage = "image_generation"
        on_stage_changed(stage)

    if stage == "image_generation":
        with task_control.controlled(project.id, "image_generation"):
            image_generation_service.generate_project_images(session, project)
        image_assignment_service.assign_generated_images(session, project)
        stage = "scene_render"
        on_stage_changed(stage)

    if stage == "scene_render":
        with task_control.controlled(project.id, "scene_render"):
            scene_renderer.render_all_scenes(session, project)
        stage = "visual_track"
        on_stage_changed(stage)

    if stage == "visual_track":
        with task_control.controlled(project.id, "visual_track"):
            visual_track_composer.compose_visual_track(session, project)
        stage = "final_render"
        on_stage_changed(stage)

    if stage == "final_render":
        with task_control.controlled(project.id, "final_render"):
            final_renderer.compose_final_video(session, project)
        stage = "quality_check"
        on_stage_changed(stage)

    if stage == "quality_check":
        with task_control.controlled(project.id, "quality_check"):
            report = qa_service.run_quality_check(session, project)
        if not report.get("passed"):
            error_count = report.get("summary", {}).get("error_count", 0)
            raise RuntimeError(f"Final video quality check failed with {error_count} errors")
        on_stage_changed("completed")


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


def regenerate_storyboard(session: Session, project: Project) -> dict:
    _clear_project_visual_data(session, project.id)
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


def _clear_project_visual_data(session: Session, project_id: str) -> None:
    from app.models.media import GeneratedImageVariant, SceneAssignment

    for assignment in session.exec(
        select(SceneAssignment).where(SceneAssignment.project_id == project_id)
    ).all():
        session.delete(assignment)
    for variant in session.exec(
        select(GeneratedImageVariant).where(GeneratedImageVariant.project_id == project_id)
    ).all():
        session.delete(variant)
    for scene in _scenes(session, project_id):
        session.delete(scene)
    session.commit()
