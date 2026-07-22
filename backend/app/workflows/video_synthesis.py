from collections.abc import Callable
from sqlmodel import Session, select

from app.infrastructure import gpu_resource, process_runner as task_control
from app.models.media import LIBRARY_ROLE_SEMANTIC
from app.models.project import Project
from app.models.storyboard import SubtitleCue, VisualScene
from app.services.media_library import ingestion_service, retrieval_service
from app.services.image_generation import image_generation_service, image_selection_service
from app.services.rendering import final_renderer, scene_renderer, visual_track_composer
from app.services.rendering import timeline_composer
from app.services.quality import qa_service
from app.services.storyboard import storyboard_service
from app.services.projects import fcpxml_export_service, prproj_export_service, project_service


StageChanged = Callable[[str], None]
STAGES = {
    "storyboard",
    "asset_search",
    "asset_review",
    "image_generation",
    "image_review",
    "scene_render",
    "visual_track",
    "final_render",
    "quality_check",
    "quality_review",
    "fcpxml_export",
    "prproj_export",
    "editable_export",
    "completed",
}


class ReviewRequired(RuntimeError):
    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage


def run_video_synthesis(
    session: Session,
    project: Project,
    current_stage: str,
    on_stage_changed: StageChanged,
) -> None:
    stage = current_stage or "storyboard"
    if stage not in STAGES:
        raise ValueError(f"Unknown video synthesis stage: {stage}")

    if stage == "storyboard":
        regenerate_storyboard(session, project)
        stage = (
            "image_generation"
            if project_service.get_project_video_mode(project)
            == project_service.VIDEO_MODE_AI_GENERATED_IMAGES
            else "asset_search"
        )
        on_stage_changed(stage)

    if stage == "image_generation":
        with task_control.controlled(project.id, "image_generation"):
            image_generation_service.generate_project_images(session, project)
        image_selection_service.score_project_images(session, project)
        review_required = (
            project_service.get_semantic_review_mode(project)
            == project_service.SEMANTIC_REVIEW_MANUAL
        )
        for scene in _scenes(session, project.id):
            image_selection_service.auto_assign_best_image(
                session, project, scene.id, review_required=review_required
            )
        stage = "image_review"
        on_stage_changed(stage)

    if stage == "image_review":
        missing = assignment_gap(session, project.id)
        if missing:
            _raise_assignment_gap(project, "image_review", missing, "生成图片")
        stage = output_stage(project)
        on_stage_changed(stage)

    if stage == "asset_search":
        review_required = (
            project_service.get_semantic_review_mode(project)
            == project_service.SEMANTIC_REVIEW_MANUAL
        )
        with gpu_resource.exclusive_gpu(f"project-media-search:project:{project.id}"):
            _ingest_configured_assets(session, project)
            scenes = _scenes(session, project.id)
            for scene in scenes:
                retrieval_service.search_scene_candidates(session, project, scene.id)
                retrieval_service.auto_assign_qualified_candidates(
                    session, project, scene.id, review_required=review_required
                )
        stage = "asset_review"
        on_stage_changed(stage)

    if stage == "asset_review":
        missing = assignment_gap(session, project.id)
        if missing:
            _raise_assignment_gap(project, "asset_review", missing, "素材")
        stage = output_stage(project)
        on_stage_changed(stage)

    if stage == "scene_render":
        scene_renderer.render_all_scenes(session, project)
        stage = "visual_track"
        on_stage_changed(stage)

    if stage == "fcpxml_export":
        fcpxml_export_service.export_project_fcpxml(session, project)
        on_stage_changed("completed")
        return

    if stage == "prproj_export":
        prproj_export_service.export_project_prproj(session, project)
        on_stage_changed("completed")
        return

    if stage == "editable_export":
        fcpxml_export_service.export_project_fcpxml(session, project)
        prproj_export_service.export_project_prproj(session, project)
        on_stage_changed("completed")
        return

    if stage == "visual_track":
        visual_track_composer.compose_visual_track(session, project)
        stage = "final_render"
        on_stage_changed(stage)

    if stage == "final_render":
        final_renderer.compose_final_video(session, project)
        stage = "quality_check"
        on_stage_changed(stage)

    if stage in {"quality_check", "quality_review"}:
        report = qa_service.run_quality_check(session, project)
        if not report.get("passed"):
            error_count = report.get("summary", {}).get("error_count", 0)
            raise RuntimeError(f"自动质量检查未通过：{error_count} 个错误")
        on_stage_changed("completed")


def initial_stage(session: Session, project_id: str) -> str:
    project = session.get(Project, project_id)
    scenes = _scenes(session, project_id)
    if not scenes:
        return "storyboard"
    if assignment_gap(session, project_id) == 0:
        return output_stage(project) if project else "scene_render"
    if project and project_service.get_project_video_mode(project) == project_service.VIDEO_MODE_AI_GENERATED_IMAGES:
        return "image_generation"
    return "asset_search"


def regenerate_storyboard(session: Session, project: Project) -> dict:
    retrieval_service.clear_project_scene_data(session, project.id)
    return storyboard_service.generate_storyboard(session, project)


def assignment_gap(session: Session, project_id: str) -> int:
    scenes = _scenes(session, project_id)
    incomplete = 0
    for scene in scenes:
        coverage = timeline_composer.scene_coverage(session, scene)
        if not coverage["complete"] or any(
            not item.manual_confirmed for item in coverage["assignments"]
        ):
            incomplete += 1
    return incomplete


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


def _ingest_configured_assets(session: Session, project: Project) -> None:
    # media_video_dir belongs to the landscape rough-cut mode. Intelligent
    # synthesis only ingests assets explicitly classified for semantic search.
    for asset in ingestion_service.list_assets(
        session, limit=1000, library_role=LIBRARY_ROLE_SEMANTIC
    ):
        if any(
            shot.get("vector_id") is None or shot.get("vector_model") != ingestion_service.MODEL_NAME
            for shot in asset["shots"]
        ):
            ingestion_service.ingest_asset(session, asset["id"])


def output_stage(project: Project) -> str:
    output_format = project_service.get_video_output_format(project)
    if output_format == project_service.VIDEO_OUTPUT_FCPXML:
        return "fcpxml_export"
    if output_format == project_service.VIDEO_OUTPUT_PRPROJ:
        return "prproj_export"
    if output_format == project_service.VIDEO_OUTPUT_EDITABLE_BOTH:
        return "editable_export"
    return "scene_render"


def _raise_assignment_gap(project: Project, stage: str, missing: int, label: str) -> None:
    message = f"仍有 {missing} 个分镜缺少可用{label}"
    if (
        project_service.get_semantic_review_mode(project)
        == project_service.SEMANTIC_REVIEW_MANUAL
    ):
        raise ReviewRequired(stage, f"{message}，需要人工审核")
    raise RuntimeError(f"{message}，自动流程无法继续")
