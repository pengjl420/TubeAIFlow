from collections.abc import Callable
from pathlib import Path

from sqlmodel import Session, select

from app.models.project import Project
from app.models.narration import Segment
from app.models.storyboard import SubtitleCue
from app.infrastructure import process_runner as task_control
from app.infrastructure.ffmpeg import ensure_ffmpeg_available
from app.config import get_settings
from app.infrastructure.project_layout import (
    get_final_audio_path,
    get_final_srt_path,
    get_final_video_path,
    get_output_stem,
    get_project_work_dir,
)
from app.services.narration import audio_service, srt_service, timeline_service, tts_service
from app.services.projects import project_service
from app.services.quality import qa_service
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
    ensure_ffmpeg_available()
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
            timeline_service.build_timeline(session, project)
            segments = session.exec(
                select(Segment)
                .where(Segment.project_id == project.id)
                .order_by(Segment.segment_index)
            ).all()
            srt_service.create_full_srt(project, list(segments), session=session)
        project.status = "narration_ready"
        session.add(project)
        session.commit()
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

    if stage in video_synthesis.STAGES and stage != "completed":
        video_synthesis.run_video_synthesis(session, project, stage, on_stage_changed)


def _stage_after_narration(project: Project, include_video: bool) -> str:
    video_mode = (
        project_service.get_project_video_mode(project)
        if include_video
        else project_service.VIDEO_MODE_NONE
    )
    if video_mode == project_service.VIDEO_MODE_LANDSCAPE:
        return "video"
    if video_mode == project_service.VIDEO_MODE_AI_GENERATED_IMAGES:
        return "storyboard"
    return "completed"


def initial_stage(session: Session, project: Project, include_video: bool) -> str:
    """Return the earliest incomplete stage for a one-click continuation."""
    segments = list(
        session.exec(
            select(Segment)
            .where(Segment.project_id == project.id)
            .order_by(Segment.segment_index)
        ).all()
    )
    if not segments:
        return "segmenting"
    if any(
        item.status != "completed"
        or not item.audio_path
        or not Path(item.audio_path).is_file()
        for item in segments
    ):
        return "tts"

    settings = get_settings()
    if not get_final_audio_path(project, settings.workspace_dir).is_file():
        return "audio_merge"
    if not _narration_outputs_exist(session, project):
        return "subtitles"

    next_stage = _stage_after_narration(project, include_video)
    if next_stage in video_synthesis.STAGES:
        if _final_output_exists(project):
            return _stage_after_existing_output(project)
        return video_synthesis.initial_stage(session, project.id)
    if next_stage == "video" and get_final_video_path(project, settings.workspace_dir).is_file():
        return _stage_after_existing_output(project)
    return next_stage


def _narration_outputs_exist(session: Session, project: Project) -> bool:
    settings = get_settings()
    work_dir = get_project_work_dir(project, settings.workspace_dir)
    stem = get_output_stem(project)
    timeline_paths = (
        work_dir / "timeline" / f"{stem}_timeline.json",
        work_dir / "timeline" / "timeline.json",
    )
    has_cues = session.exec(
        select(SubtitleCue.id).where(SubtitleCue.project_id == project.id).limit(1)
    ).first() is not None
    return (
        get_final_srt_path(project, settings.workspace_dir).is_file()
        and any(path.is_file() for path in timeline_paths)
        and has_cues
    )


def _final_output_exists(project: Project) -> bool:
    return get_final_video_path(project, get_settings().workspace_dir).is_file()


def _stage_after_existing_output(project: Project) -> str:
    report = qa_service.read_report(project)
    return "completed" if report and report.get("passed") else "quality_check"
