from collections.abc import Callable

from sqlmodel import Session, select

from app.models.project import Project
from app.models.segment import Segment
from app.services import (
    audio_service,
    project_service,
    srt_service,
    timeline_service,
    translate_service,
    tts_service,
    video_service,
)


StageChanged = Callable[[str], None]


def run_project_generation(
    session: Session,
    project: Project,
    current_stage: str,
    include_video: bool,
    on_stage_changed: StageChanged,
) -> None:
    """Run one project's generation stages from its persisted checkpoint."""
    stage = current_stage or "segmenting"
    if stage not in {"segmenting", "tts", "audio_merge", "subtitles", "video", "completed"}:
        raise ValueError(f"Unknown generation stage: {stage}")

    if stage == "segmenting":
        project_service.create_segments(session, project)
        stage = "tts"
        on_stage_changed(stage)

    if stage == "tts":
        segments = tts_service.generate_project_tts(session, project)
        failed = [item for item in segments if item.status == "failed"]
        if failed:
            raise RuntimeError(f"TTS 有 {len(failed)} 段生成失败")
        stage = "audio_merge"
        on_stage_changed(stage)

    if stage == "audio_merge":
        audio_service.merge_project_audio(session, project)
        stage = "subtitles"
        on_stage_changed(stage)

    if stage == "subtitles":
        _create_subtitles(session, project)
        stage = "video" if include_video else "completed"
        on_stage_changed(stage)

    if stage == "video":
        try:
            video_service.compose_video(session, project)
        except (OSError, RuntimeError, ValueError) as exc:
            try:
                video_service.mark_video_progress_failed(project, str(exc))
            except OSError:
                pass
            raise
        on_stage_changed("completed")


def _create_subtitles(session: Session, project: Project) -> None:
    timeline_service.build_timeline(session, project)
    segments = list(
        session.exec(
            select(Segment)
            .where(Segment.project_id == project.id)
            .order_by(Segment.segment_index)
        ).all()
    )
    _, zh_cues = srt_service.create_full_srt_with_cues(project, segments)
    _, translations = translate_service.translate_subtitle_cues_to_english(project, zh_cues)
    srt_service.create_english_srt_from_chinese_cues(project, zh_cues, translations)
    project.status = "en_subtitle_created"
    session.add(project)
    session.commit()
