from collections.abc import Callable
import json
from pathlib import Path

from sqlmodel import Session, select

from app.models.project import Project
from app.models.narration import Segment
from app.models.storyboard import SubtitleCue, VisualScene
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
from app.workflows.engine import WorkflowContext, WorkflowGraph, WorkflowStep
from app.domain.states import ResourceClass


StageChanged = Callable[[str], None]


def regenerate_segment_and_refresh_outputs(
    session: Session,
    project: Project,
    segment: Segment,
) -> Segment:
    """Regenerate one segment and keep completed narration artifacts consistent."""
    locked_indexes = _locked_audio_scene_indexes(session, project.id, segment.id)
    if locked_indexes:
        raise ValueError(
            "Scene audio is locked: " + ", ".join(str(index) for index in locked_indexes)
        )
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
    supported_stages = {*_NARRATION_GRAPH.stages, "completed", *video_synthesis.STAGES}
    if stage not in supported_stages:
        raise ValueError(f"Unknown generation stage: {stage}")
    if stage in {"segmenting", "tts", "audio_merge"}:
        locked_indexes = _locked_audio_scene_indexes(session, project.id)
        if locked_indexes:
            raise ValueError(
                "Scene audio is locked: " + ", ".join(str(index) for index in locked_indexes)
            )
    stage = _NARRATION_GRAPH.execute(
        WorkflowContext(
            session=session,
            project=project,
            include_video=include_video,
            artifact_exists=lambda name: _artifact_exists(session, project, name),
        ),
        stage,
        on_stage_changed,
    )
    if stage in video_synthesis.STAGES and stage != "completed":
        video_synthesis.run_video_synthesis(session, project, stage, on_stage_changed)


def _locked_audio_scene_indexes(
    session: Session,
    project_id: str,
    source_segment_id: str | None = None,
) -> list[int]:
    scenes = list(
        session.exec(
            select(VisualScene).where(
                VisualScene.project_id == project_id,
                VisualScene.locked_audio.is_(True),
            )
        ).all()
    )
    if source_segment_id is None:
        return sorted(scene.scene_index for scene in scenes)
    cue_ids = {
        cue_id
        for cue_id in session.exec(
            select(SubtitleCue.id).where(
                SubtitleCue.project_id == project_id,
                SubtitleCue.source_segment_id == source_segment_id,
            )
        ).all()
    }
    matched = []
    for scene in scenes:
        try:
            scene_cue_ids = set(json.loads(scene.subtitle_ids_json))
        except (TypeError, json.JSONDecodeError):
            scene_cue_ids = set()
        if cue_ids.intersection(scene_cue_ids):
            matched.append(scene.scene_index)
    return sorted(matched)


def _segmenting_step(context: WorkflowContext) -> str:
    project_service.create_segments(context.session, context.project)
    return "tts"


def _tts_step(context: WorkflowContext) -> str:
    with task_control.controlled(context.project.id, "tts"):
        segments = tts_service.generate_project_tts(context.session, context.project)
    failed = [item for item in segments if item.status == "failed"]
    if failed:
        raise RuntimeError(f"TTS 有 {len(failed)} 段生成失败")
    return "audio_merge"


def _audio_merge_step(context: WorkflowContext) -> str:
    with task_control.controlled(context.project.id, "audio_merge"):
        audio_service.merge_project_audio(context.session, context.project)
    return "subtitles"


def _subtitles_step(context: WorkflowContext) -> str:
    with task_control.controlled(context.project.id, "subtitles"):
        timeline_service.build_timeline(context.session, context.project)
        segments = context.session.exec(
            select(Segment)
            .where(Segment.project_id == context.project.id)
            .order_by(Segment.segment_index)
        ).all()
        srt_service.create_full_srt(
            context.project, list(segments), session=context.session
        )
    context.project.status = "narration_ready"
    context.session.add(context.project)
    context.session.commit()
    return _stage_after_narration(context.project, context.include_video)


def _video_step(context: WorkflowContext) -> str:
    try:
        with task_control.controlled(context.project.id, "video"):
            rough_cut_service.compose_video(context.session, context.project)
    except task_control.TaskCancelledError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        try:
            rough_cut_service.mark_video_progress_failed(context.project, str(exc))
        except OSError:
            pass
        raise
    return "completed"


_NARRATION_GRAPH = WorkflowGraph(
    (
        WorkflowStep("segmenting", _segmenting_step, output_artifacts=("segments",)),
        WorkflowStep(
            "tts",
            _tts_step,
            resource_class=ResourceClass.GPU,
            depends_on=("segmenting",),
            input_artifacts=("segments",),
            output_artifacts=("segment_audio",),
            cacheable=True,
            cached_next_stage="audio_merge",
        ),
        WorkflowStep(
            "audio_merge",
            _audio_merge_step,
            resource_class=ResourceClass.FFMPEG,
            depends_on=("tts",),
            input_artifacts=("segment_audio",),
            output_artifacts=("narration_audio",),
        ),
        WorkflowStep(
            "subtitles",
            _subtitles_step,
            depends_on=("audio_merge",),
            input_artifacts=("narration_audio",),
            output_artifacts=("subtitle_timeline",),
        ),
        WorkflowStep(
            "video",
            _video_step,
            resource_class=ResourceClass.FFMPEG,
            depends_on=("subtitles",),
            output_artifacts=("final_video",),
        ),
    )
)


def _stage_after_narration(project: Project, include_video: bool) -> str:
    video_mode = (
        project_service.get_project_video_mode(project)
        if include_video
        else project_service.VIDEO_MODE_NONE
    )
    if video_mode == project_service.VIDEO_MODE_LANDSCAPE:
        return "video"
    if video_mode in {
        project_service.VIDEO_MODE_AI_GENERATED_IMAGES,
        project_service.VIDEO_MODE_AI_LANDSCAPE_MIX,
    }:
        return "storyboard"
    return "completed"


def _artifact_exists(session: Session, project: Project, name: str) -> bool:
    segments = list(
        session.exec(
            select(Segment)
            .where(Segment.project_id == project.id)
            .order_by(Segment.segment_index)
        ).all()
    )
    if name == "segments":
        return bool(segments)
    if name == "segment_audio":
        return bool(segments) and all(
            item.status == "completed"
            and bool(item.audio_path)
            and Path(item.audio_path or "").is_file()
            for item in segments
        )
    if name == "narration_audio":
        return get_final_audio_path(project, get_settings().workspace_dir).is_file()
    if name == "subtitle_timeline":
        return _narration_outputs_exist(session, project)
    if name == "final_video":
        return get_final_video_path(project, get_settings().workspace_dir).is_file()
    return False


def resource_class(stage: str) -> ResourceClass:
    if stage in _NARRATION_GRAPH.stages:
        return _NARRATION_GRAPH.resource_class(stage)
    if stage in video_synthesis.STAGES and stage != "completed":
        return video_synthesis.resource_class(stage)
    raise ValueError(f"Unknown generation stage: {stage}")


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
