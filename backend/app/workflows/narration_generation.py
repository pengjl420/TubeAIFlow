from collections.abc import Callable

from sqlmodel import Session, select

from app.models.project import Project
from app.models.narration import Segment
from app.infrastructure import process_runner as task_control
from app.config import get_settings
from app.infrastructure.project_layout import get_final_audio_path
from app.services.narration import audio_service, srt_service, timeline_service, tts_service
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
        # Rebuild in dependency order. merge_project_audio atomically replaces the
        # prior WAV, so a failed FFmpeg run cannot destroy the last valid output.
        audio_service.merge_project_audio(session, project)
        _create_subtitles(session, project)
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
        stage = "subtitles"
        on_stage_changed(stage)

    if stage == "subtitles":
        with task_control.controlled(project.id, "subtitles"):
            _create_subtitles(session, project)
        video_mode = (
            project_service.get_project_video_mode(project)
            if include_video
            else project_service.VIDEO_MODE_NONE
        )
        if video_mode == project_service.VIDEO_MODE_LANDSCAPE:
            stage = "video"
        elif video_mode == project_service.VIDEO_MODE_AI_SEMANTIC:
            stage = "storyboard"
        else:
            stage = "completed"
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

    if stage in video_synthesis.STAGES - {"completed"}:
        video_synthesis.run_video_synthesis(session, project, stage, on_stage_changed)


def _create_subtitles(session: Session, project: Project) -> None:
    timeline_service.build_timeline(session, project)
    segments = list(
        session.exec(
            select(Segment)
            .where(Segment.project_id == project.id)
            .order_by(Segment.segment_index)
        ).all()
    )
    srt_service.create_full_srt(project, segments, session=session)
    project.status = "narration_ready"
    session.add(project)
    session.commit()
