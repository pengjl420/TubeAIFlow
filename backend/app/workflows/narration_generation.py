from collections.abc import Callable

from sqlmodel import Session, select

from app.models.project import Project
from app.models.narration import Segment
from app.infrastructure import process_runner as task_control
from app.services.narration import audio_service, srt_service, timeline_service, tts_service
from app.services.projects import project_service
from app.services.rendering import rough_cut_service


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
        stage = "video" if include_video else "completed"
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


def _create_subtitles(session: Session, project: Project) -> None:
    timeline_service.build_timeline(session, project)
    segments = list(
        session.exec(
            select(Segment)
            .where(Segment.project_id == project.id)
            .order_by(Segment.segment_index)
        ).all()
    )
    srt_service.create_full_srt(project, segments)
    project.status = "zh_subtitle_created"
    session.add(project)
    session.commit()
