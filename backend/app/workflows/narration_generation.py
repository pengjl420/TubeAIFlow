from collections.abc import Callable

from sqlmodel import Session

from app.models.project import Project
from app.models.narration import Segment
from app.infrastructure import process_runner as task_control
from app.config import get_settings
from app.infrastructure.project_layout import get_final_audio_path
from app.services.narration import audio_service, tts_service
from app.services.projects import project_service
from app.services.rendering import rough_cut_service
from app.workflows import video_synthesis


StageChanged = Callable[[str], None]


def regenerate_segment_and_refresh_outputs(
    session: Session,
    project: Project,
    segment: Segment,
) -> Segment:
    """Regenerate one segment and keep completed narration artifacts consistent."""
    full_audio_path = get_final_audio_path(project, get_settings().workspace_dir)
    refresh_completed_outputs = full_audio_path.is_file()

    regenerated = tts_service.regenerate_segment_tts(session, project, segment)
    if refresh_completed_outputs:
        # Keep the merged narration consistent after a single segment changes.
        audio_service.merge_project_audio(session, project)
    return regenerated


def run_project_generation(
    session: Session,
    project: Project,
    current_stage: str,
    include_video: bool,
    on_stage_changed: StageChanged,
) -> None:
    """Run one project's generation stages from its persisted checkpoint."""
    stage = current_stage or "segmenting"
    supported_stages = {
        "segmenting", "tts", "audio_merge", "subtitles", "video", "completed",
        *video_synthesis.STAGES,
    }
    if stage not in supported_stages:
        raise ValueError(f"Unknown generation stage: {stage}")

    if stage == "segmenting":
        project_service.create_segments(session, project)
        stage = "tts"
        on_stage_changed(stage)

    if stage == "tts":
        with task_control.controlled(project.id, "tts"):
            segments = tts_service.generate_project_tts(session, project)
        failed = [item for item in segments if item.status == "failed"]
        if failed:
            raise RuntimeError(f"TTS 有 {len(failed)} 段生成失败")
        stage = "audio_merge"
        on_stage_changed(stage)

    if stage == "audio_merge":
        with task_control.controlled(project.id, "audio_merge"):
            audio_service.merge_project_audio(session, project)
        project.status = "narration_ready"
        session.add(project)
        session.commit()
        stage = _stage_after_narration(project, include_video)
        on_stage_changed(stage)

    # Compatibility for tasks created by older versions. Subtitles and their
    # public timeline are no longer production stages.
    if stage == "subtitles":
        stage = _stage_after_narration(project, include_video)
        on_stage_changed(stage)

    if stage == "video":
        try:
            with task_control.controlled(project.id, "video"):
                rough_cut_service.compose_video(session, project)
        except task_control.TaskCancelledError:
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            try:
                rough_cut_service.mark_video_progress_failed(project, str(exc))
            except OSError:
                pass
            raise
        on_stage_changed("completed")

    if stage in {"storyboard", "asset_search", "asset_review", "image_generation", "image_review", "scene_render", "visual_track", "final_render", "quality_check", "quality_review", "fcpxml_export", "prproj_export", "editable_export"}:
        video_synthesis.run_video_synthesis(session, project, stage, on_stage_changed)


def _stage_after_narration(project: Project, include_video: bool) -> str:
    video_mode = (
        project_service.get_project_video_mode(project)
        if include_video
        else project_service.VIDEO_MODE_NONE
    )
    output_format = project_service.get_video_output_format(project)
    if (
        video_mode in {project_service.VIDEO_MODE_NONE, project_service.VIDEO_MODE_LANDSCAPE}
        and output_format != project_service.VIDEO_OUTPUT_MP4
    ):
        return video_synthesis.output_stage(project)
    if video_mode == project_service.VIDEO_MODE_LANDSCAPE:
        return "video"
    if video_mode in {
        project_service.VIDEO_MODE_AI_SEMANTIC,
        project_service.VIDEO_MODE_AI_GENERATED_IMAGES,
    }:
        return "storyboard"
    return "completed"
