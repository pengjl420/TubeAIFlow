import json
import uuid
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

from app.config import get_settings
from app.models.project import Project
from app.models.narration import Segment
from app.models.batch import BatchItem, BatchJob
from app.models.media import GeneratedImageVariant, MediaFile, MediaShot, SceneAssignment
from app.models.task import TaskRun
from app.providers import ProviderCategory, provider_registry
from app.models.storyboard import SubtitleCue, VisualScene
from app.infrastructure.file_storage import ensure_inside_any, project_dir
from app.infrastructure.recycle_bin import move_existing_to_recycle_bin
from app.infrastructure.project_layout import (
    ensure_project_dirs,
    get_final_audio_path,
    get_final_fcpxml_path,
    get_final_premiere_xml_path,
    get_final_prproj_path,
    get_final_srt_path,
    get_final_video_path,
    get_legacy_project_work_dir,
    get_output_stem,
    get_project_output_dir,
    get_project_work_dir,
    load_project_config,
    safe_filename_stem,
)
from app.services.narration.segmenter import split_script, split_script_with_ai
from app.services.narration.text_cleaner import clean_script
from app.services.projects.project_descriptor_service import write_project_descriptor
from app.shared.time import elapsed_seconds, utc_now_iso


DEFAULT_TTS_ENGINE = "index_tts"
SUPPORTED_TTS_ENGINES = provider_registry.legacy_ids(ProviderCategory.TTS)
SEGMENTATION_MODE_NEWLINE = "newline"
SEGMENTATION_MODE_AI = "ai"
SUPPORTED_SEGMENTATION_MODES = {SEGMENTATION_MODE_NEWLINE, SEGMENTATION_MODE_AI}
STORYBOARD_MODE_AI = "ai"
STORYBOARD_MODE_SEGMENTS = "segments"
SUPPORTED_STORYBOARD_MODES = {STORYBOARD_MODE_AI, STORYBOARD_MODE_SEGMENTS}
VIDEO_MODE_NONE = "none"
VIDEO_MODE_LANDSCAPE = "landscape"
VIDEO_MODE_AI_GENERATED_IMAGES = "ai_generated_images"
VIDEO_MODE_AI_LANDSCAPE_MIX = "ai_landscape_mix"
VIDEO_OUTPUT_MP4 = "mp4"
VIDEO_OUTPUT_FCPXML = "fcpxml"
VIDEO_OUTPUT_PRPROJ = "prproj"
VIDEO_OUTPUT_EDITABLE_BOTH = "editable_both"
SUPPORTED_VIDEO_OUTPUT_FORMATS = {
    VIDEO_OUTPUT_MP4,
    VIDEO_OUTPUT_FCPXML,
    VIDEO_OUTPUT_PRPROJ,
    VIDEO_OUTPUT_EDITABLE_BOTH,
}
SUPPORTED_VIDEO_MODES = {
    VIDEO_MODE_NONE,
    VIDEO_MODE_LANDSCAPE,
    VIDEO_MODE_AI_GENERATED_IMAGES,
    VIDEO_MODE_AI_LANDSCAPE_MIX,
}
EDITABLE_STATUSES = {"created", "script_imported", "segmented"}
GENERATING_STATUSES = {
    "narration_in_progress",
    "video_in_progress",
    "segmenting",
    "tts",
    "tts_running",
    "audio_merge",
    "subtitles",
    "rendering",
    "video_composing",
}


def create_project(session: Session, name: str, config: dict | None = None) -> Project:
    settings = get_settings()
    project_id = uuid.uuid4().hex[:12]
    output_dir = settings.workspace_dir / "projects"
    project_directory_name = _available_project_directory_name(
        output_dir, name, project_id
    )
    project = Project(
        id=project_id,
        name=name,
        output_dir=str(output_dir),
        status="created",
        config_json=json.dumps(
            {
                "tts_engine": DEFAULT_TTS_ENGINE,
                "segmentation_mode": SEGMENTATION_MODE_NEWLINE,
                "storyboard_mode": STORYBOARD_MODE_AI,
                "storyboard_transition_enabled": True,
                "project_directory_name": project_directory_name,
                **(config or {}),
            },
            ensure_ascii=False,
        ),
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    ensure_project_dirs(get_project_work_dir(project, settings.workspace_dir))
    write_project_descriptor(project)
    return project


def project_response(project: Project, metrics: dict | None = None) -> dict:
    """Return the API representation while keeping config_json for old clients."""
    return {
        **project.model_dump(),
        "config": load_project_config(project),
        **(metrics or _empty_project_metrics()),
    }


def list_projects(session: Session) -> list[dict]:
    projects = list(session.exec(select(Project).order_by(Project.created_at.desc())).all())
    metrics = get_project_metrics(session, [project.id for project in projects])
    return [project_response(project, metrics.get(project.id)) for project in projects]


def get_project_response(session: Session, project: Project) -> dict:
    metrics = get_project_metrics(session, [project.id])
    return project_response(project, metrics.get(project.id))


def get_project_metrics(session: Session, project_ids: list[str]) -> dict[str, dict]:
    """Aggregate persisted audio and latest-run timing without probing files per request."""
    if not project_ids:
        return {}
    metrics = {project_id: _empty_project_metrics() for project_id in project_ids}
    segments = session.exec(select(Segment).where(Segment.project_id.in_(project_ids))).all()
    for segment in segments:
        if segment.duration is not None:
            metrics[segment.project_id]["audio_duration_seconds"] += max(0.0, float(segment.duration))

    tasks = session.exec(
        select(TaskRun)
        .where(TaskRun.project_id.in_(project_ids))
        .order_by(TaskRun.queue_sequence)
    ).all()
    latest_tasks: dict[str, TaskRun] = {}
    for task in tasks:
        latest_tasks[task.project_id] = task
    for project_id, task in latest_tasks.items():
        metrics[project_id].update(
            {
                "workflow_started_at": task.started_at,
                "workflow_finished_at": task.finished_at,
                "workflow_duration_seconds": elapsed_seconds(task.started_at, task.finished_at),
                "latest_task_status": task.status,
            }
        )
    for item in metrics.values():
        item["audio_duration_seconds"] = round(item["audio_duration_seconds"], 3)
    return metrics


def _empty_project_metrics() -> dict:
    return {
        "audio_duration_seconds": 0.0,
        "workflow_started_at": None,
        "workflow_finished_at": None,
        "workflow_duration_seconds": None,
        "latest_task_status": None,
    }


def get_project(session: Session, project_id: str) -> Project | None:
    return session.get(Project, project_id)


def is_project_editable(project: Project) -> bool:
    return project.status in EDITABLE_STATUSES


def normalize_video_mode(video_mode: str | None, include_video: bool = False) -> str:
    """Resolve the explicit video mode while preserving old include_video projects."""
    normalized = str(video_mode or "").strip().lower()
    if not normalized:
        return VIDEO_MODE_LANDSCAPE if include_video else VIDEO_MODE_NONE
    if normalized not in SUPPORTED_VIDEO_MODES:
        raise ValueError("Unsupported video generation mode")
    return normalized


def get_project_video_mode(project: Project) -> str:
    config = load_project_config(project)
    return normalize_video_mode(
        config.get("video_mode"),
        bool(config.get("include_video", False)),
    )


def normalize_segmentation_mode(mode: str | None) -> str:
    normalized = str(mode or SEGMENTATION_MODE_NEWLINE).strip().lower()
    if normalized not in SUPPORTED_SEGMENTATION_MODES:
        raise ValueError("Unsupported transcript segmentation mode")
    return normalized


def get_segmentation_mode(project: Project) -> str:
    return normalize_segmentation_mode(load_project_config(project).get("segmentation_mode"))


def normalize_storyboard_mode(mode: str | None) -> str:
    normalized = str(mode or STORYBOARD_MODE_AI).strip().lower()
    if normalized not in SUPPORTED_STORYBOARD_MODES:
        raise ValueError("Unsupported storyboard segmentation mode")
    return normalized


def get_storyboard_mode(project: Project) -> str:
    return normalize_storyboard_mode(load_project_config(project).get("storyboard_mode"))


def normalize_video_output_format(value: str | None) -> str:
    normalized = str(value or VIDEO_OUTPUT_MP4).strip().lower()
    if normalized not in SUPPORTED_VIDEO_OUTPUT_FORMATS:
        raise ValueError(f"Unsupported video output format: {value}")
    return normalized


def get_video_output_format(project: Project) -> str:
    configured = load_project_config(project).get("video_output_format")
    # The simplified flow always delivers a rendered MP4.
    if configured is None:
        return VIDEO_OUTPUT_MP4
    return normalize_video_output_format(configured)


def delete_project(session: Session, project: Project) -> dict:
    active_task = session.exec(
        select(TaskRun).where(
            TaskRun.project_id == project.id,
            TaskRun.status.in_({"queued", "running", "paused"}),
        )
    ).first()
    if active_task or project.status in GENERATING_STATUSES:
        raise ValueError("生成中的项目请先强制停止，确认停止后再删除")

    artifact_paths = _prepare_project_deletion(session, project)
    recycled_paths = move_existing_to_recycle_bin(artifact_paths)

    batch_items = list(
        session.exec(select(BatchItem).where(BatchItem.project_id == project.id)).all()
    )
    affected_batch_ids = {item.batch_id for item in batch_items}
    for task in session.exec(select(TaskRun).where(TaskRun.project_id == project.id)).all():
        session.delete(task)
    for segment in session.exec(select(Segment).where(Segment.project_id == project.id)).all():
        session.delete(segment)
    for cue in session.exec(
        select(SubtitleCue).where(SubtitleCue.project_id == project.id)
    ).all():
        session.delete(cue)
    for assignment in session.exec(
        select(SceneAssignment).where(SceneAssignment.project_id == project.id)
    ).all():
        session.delete(assignment)
    generated_variants = list(
        session.exec(
            select(GeneratedImageVariant).where(GeneratedImageVariant.project_id == project.id)
        ).all()
    )
    generated_media_ids = {item.media_file_id for item in generated_variants if item.media_file_id}
    for variant in generated_variants:
        session.delete(variant)
    for media_id in generated_media_ids:
        for shot in session.exec(select(MediaShot).where(MediaShot.media_file_id == media_id)).all():
            session.delete(shot)
        media_file = session.get(MediaFile, media_id)
        if media_file and media_file.provider == "local_image_generation":
            session.delete(media_file)
    for scene in session.exec(
        select(VisualScene).where(VisualScene.project_id == project.id)
    ).all():
        session.delete(scene)
    for item in batch_items:
        session.delete(item)
    session.delete(project)
    session.flush()

    for batch_id in affected_batch_ids:
        batch = session.get(BatchJob, batch_id)
        if not batch:
            continue
        remaining = list(
            session.exec(select(BatchItem).where(BatchItem.batch_id == batch_id)).all()
        )
        batch.total = len(remaining)
        batch.completed = sum(item.status == "completed" for item in remaining)
        batch.failed = sum(item.status == "failed" for item in remaining)
        batch.updated_at = utc_now_iso()
        session.add(batch)

    session.commit()
    return {"project_id": project.id, "recycled_paths": recycled_paths}


def _prepare_project_deletion(session: Session, project: Project) -> list[Path]:
    """Persist deletion intent before moving recoverable files out of place.

    A retry can safely finish the database cleanup when the process exits after
    recycling files or when recycling only succeeds for a subset of paths.
    """
    config = load_project_config(project)
    deletion = config.get("_deletion")
    if isinstance(deletion, dict) and isinstance(deletion.get("artifact_paths"), list):
        artifact_paths = [Path(str(path)) for path in deletion["artifact_paths"]]
    else:
        artifact_paths = _project_artifact_paths(project)
        config["_deletion"] = {
            "requested_at": utc_now_iso(),
            "artifact_paths": [str(path) for path in artifact_paths],
        }
        project.config_json = json.dumps(config, ensure_ascii=False)
    project.status = "deleting"
    project.updated_at = utc_now_iso()
    session.add(project)
    session.commit()
    session.refresh(project)
    return artifact_paths


def _project_artifact_paths(project: Project) -> list[Path]:
    settings = get_settings()
    output_root = get_project_output_dir(project, settings.workspace_dir)
    stem = get_output_stem(project)
    paths = [
        project_dir(settings.workspace_dir, project.id),
        get_project_work_dir(project, settings.workspace_dir),
        get_legacy_project_work_dir(project, settings.workspace_dir),
        get_final_audio_path(project, settings.workspace_dir),
        output_root / f"{stem}.mp3",
        get_final_srt_path(project, settings.workspace_dir),
        get_final_video_path(project, settings.workspace_dir),
        get_final_fcpxml_path(project, settings.workspace_dir),
        get_final_premiere_xml_path(project, settings.workspace_dir),
        get_final_prproj_path(project, settings.workspace_dir),
    ]
    return list(dict.fromkeys(paths))


def save_script(session: Session, project: Project, raw_text: str) -> Project:
    if not raw_text.strip():
        raise ValueError("Script text is required")
    settings = get_settings()
    base_dir = get_project_work_dir(project, settings.workspace_dir)
    ensure_project_dirs(base_dir)
    input_dir = base_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    clean_text = clean_script(raw_text)
    stem = get_output_stem(project)
    raw_path = input_dir / f"{stem}_raw.txt"
    clean_path = input_dir / f"{stem}_clean.txt"
    raw_path.write_text(raw_text, encoding="utf-8")
    clean_path.write_text(clean_text, encoding="utf-8")

    project.script_raw_path = str(raw_path)
    project.script_clean_path = str(clean_path)
    project.status = "script_imported"
    project.updated_at = utc_now_iso()
    session.add(project)
    session.commit()
    session.refresh(project)
    write_project_descriptor(project)
    return project


def create_segments(session: Session, project: Project) -> list[Segment]:
    if not project.script_clean_path:
        raise ValueError("Project has no cleaned script")
    settings = get_settings()
    clean_path = ensure_inside_any(
        Path(project.script_clean_path),
        [
            get_project_work_dir(project, settings.workspace_dir),
            get_legacy_project_work_dir(project, settings.workspace_dir),
            project_dir(settings.workspace_dir, project.id),
        ],
    )
    if not clean_path.is_file():
        raise ValueError("Cleaned script file does not exist")
    clean_text = clean_path.read_text(encoding="utf-8")
    segmentation_mode = get_segmentation_mode(project)
    segment_data = (
        split_script_with_ai(clean_text)
        if segmentation_mode == SEGMENTATION_MODE_AI
        else split_script(clean_text)
    )
    if not segment_data:
        raise ValueError("Cleaned script is empty")

    existing = session.exec(select(Segment).where(Segment.project_id == project.id)).all()
    segments = [
        Segment(
            id=f"{project.id}_{item['segment_id']}",
            segment_id=item["segment_id"],
            project_id=project.id,
            segment_index=item["index"],
            text=item["text"],
            status=item["status"],
        )
        for item in segment_data
    ]
    base_dir = get_project_work_dir(project, get_settings().workspace_dir)
    ensure_project_dirs(base_dir)
    segments_dir = base_dir / "segments"
    segments_dir.mkdir(parents=True, exist_ok=True)
    (segments_dir / f"{get_output_stem(project)}_segments.json").write_text(
        json.dumps(segment_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    for segment in existing:
        session.delete(segment)
    for segment in segments:
        session.add(segment)

    project.status = "segmented"
    project.updated_at = utc_now_iso()
    session.add(project)
    session.commit()
    return segments


def save_reference_audio(
    session: Session,
    project: Project,
    source,
    original_filename: str,
    max_bytes: int = 100 * 1024 * 1024,
) -> Project:
    extension = Path(original_filename).suffix.lower()
    if extension not in {".wav", ".mp3", ".flac", ".m4a"}:
        raise ValueError("Reference audio must be WAV, MP3, FLAC, or M4A")

    base_dir = get_project_work_dir(project, get_settings().workspace_dir)
    ensure_project_dirs(base_dir)
    input_dir = base_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_path = input_dir / f"reference{extension}"
    written = 0
    try:
        with output_path.open("wb") as target:
            while chunk := source.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise ValueError("Reference audio exceeds the 100 MB limit")
                target.write(chunk)
    except Exception:
        output_path.unlink(missing_ok=True)
        raise

    had_reference_audio = bool(project.reference_audio_path)
    project.reference_audio_path = str(output_path)
    config = load_project_config(project)
    config["reference_audio_path"] = str(output_path)
    config["reference_audio_filename"] = Path(original_filename).name or output_path.name
    project.config_json = json.dumps(config, ensure_ascii=False)
    if had_reference_audio and _reset_tts_segments(session, project.id):
        project.status = "segmented"
    project.updated_at = utc_now_iso()
    session.add(project)
    session.commit()
    session.refresh(project)
    write_project_descriptor(project)
    return project


def update_output_settings(
    session: Session,
    project: Project,
    output_dir: str,
    output_filename: str,
) -> Project:
    if not output_dir.strip():
        raise ValueError("Output directory is required")
    directory = Path(output_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)

    config = load_project_config(project)
    if not str(config.get("project_directory_name") or "").strip():
        config["project_directory_name"] = _available_project_directory_name(
            directory,
            project.name,
            project.id,
        )
    config["output_filename"] = safe_filename_stem(output_filename or project.name or _timestamp_stem())
    project.output_dir = str(directory)
    project.config_json = json.dumps(config, ensure_ascii=False)
    ensure_project_dirs(get_project_work_dir(project, get_settings().workspace_dir))
    project.updated_at = utc_now_iso()
    session.add(project)
    session.commit()
    session.refresh(project)
    write_project_descriptor(project)
    return project


def update_project_settings(
    session: Session,
    project: Project,
    name: str,
    output_dir: str,
    output_filename: str,
    media_video_dir: str,
    tts_engine: str = DEFAULT_TTS_ENGINE,
    reference_audio_text: str = "",
    include_video: bool = False,
    voice_profile_id: str = "",
    video_mode: str | None = None,
    video_output_format: str | None = None,
    storyboard_transition_enabled: bool = True,
    segmentation_mode: str | None = None,
    storyboard_mode: str | None = None,
) -> Project:
    project_name = name.strip()
    if not project_name:
        raise ValueError("Project name is required")
    if not output_dir.strip():
        raise ValueError("Output directory is required")
    normalized_tts_engine = tts_engine.strip().lower()
    normalized_reference_audio_text = reference_audio_text.strip()
    normalized_cosyvoice_speed = 1.0
    normalized_voice_language = "zh-CN"
    if voice_profile_id.strip():
        from app.services.narration import voice_profile_service

        selected_profile = voice_profile_service.get_profile(session, voice_profile_id.strip())
        if not selected_profile:
            raise ValueError("请选择有效的系统音色")
        profile_config = voice_profile_service.load_profile_config(selected_profile)
        normalized_tts_engine = str(profile_config.get("tts_engine") or DEFAULT_TTS_ENGINE)
        normalized_reference_audio_text = str(profile_config.get("reference_audio_text") or "").strip()
        normalized_cosyvoice_speed = voice_profile_service.profile_cosyvoice_speed(profile_config)
        normalized_voice_language = voice_profile_service.profile_language(profile_config)
    if normalized_tts_engine not in SUPPORTED_TTS_ENGINES:
        raise ValueError("Unsupported TTS engine")
    if normalized_tts_engine == "cosyvoice" and not normalized_reference_audio_text:
        raise ValueError("CosyVoice requires the reference audio transcript")

    resolved_video_mode = normalize_video_mode(video_mode, include_video)
    # Video delivery is controlled solely by video_mode/include_video. Editable
    # project files are explicit, project-level exports and never replace MP4.
    resolved_video_output_format = VIDEO_OUTPUT_MP4
    resolved_segmentation_mode = normalize_segmentation_mode(segmentation_mode)
    resolved_storyboard_mode = normalize_storyboard_mode(storyboard_mode)
    include_video = resolved_video_mode != VIDEO_MODE_NONE
    video_directory: Path | None = None
    if resolved_video_mode in {VIDEO_MODE_LANDSCAPE, VIDEO_MODE_AI_LANDSCAPE_MIX} and not media_video_dir.strip():
        raise ValueError("Video material directory is required for landscape video generation")
    if media_video_dir.strip():
        video_directory = Path(media_video_dir).expanduser().resolve()
        if not video_directory.is_dir():
            raise ValueError("Video material directory does not exist")

    output_directory = Path(output_dir).expanduser().resolve()
    output_directory.mkdir(parents=True, exist_ok=True)

    config = load_project_config(project)
    previous_tts_engine = str(config.get("tts_engine") or DEFAULT_TTS_ENGINE).strip().lower()
    previous_reference_audio_text = str(config.get("reference_audio_text") or "").strip()
    previous_cosyvoice_speed = float(config.get("cosyvoice_speed", 1.0))
    previous_voice_profile_id = str(config.get("voice_profile_id") or "")
    previous_segmentation_mode = normalize_segmentation_mode(config.get("segmentation_mode"))
    if not str(config.get("project_directory_name") or "").strip():
        config["project_directory_name"] = _available_project_directory_name(
            output_directory,
            project_name,
            project.id,
        )
    config["output_filename"] = safe_filename_stem(output_filename or project_name or _timestamp_stem())
    config["tts_engine"] = normalized_tts_engine
    config["reference_audio_text"] = normalized_reference_audio_text
    config["cosyvoice_speed"] = normalized_cosyvoice_speed
    config["voice_language"] = normalized_voice_language
    config["include_video"] = include_video
    config["video_mode"] = resolved_video_mode
    config.pop("semantic_review_mode", None)
    config["video_output_format"] = resolved_video_output_format
    config["storyboard_transition_enabled"] = bool(storyboard_transition_enabled)
    config["segmentation_mode"] = resolved_segmentation_mode
    config["storyboard_mode"] = resolved_storyboard_mode
    if video_directory:
        config["media_video_dir"] = str(video_directory)
    else:
        config.pop("media_video_dir", None)

    if voice_profile_id.strip():
        audio_path = Path(selected_profile.reference_audio_path).resolve()
        if not audio_path.is_file():
            raise ValueError("所选系统音色的参考音频文件不存在")
        config["voice_profile_id"] = selected_profile.id
        config["voice_profile_name"] = selected_profile.name
        config["voice_language"] = normalized_voice_language
        config["tts_engine"] = normalized_tts_engine
        config["reference_audio_text"] = normalized_reference_audio_text
        config["cosyvoice_speed"] = normalized_cosyvoice_speed
        config["reference_audio_filename"] = str(
            profile_config.get("original_filename") or audio_path.name
        )
        config["reference_audio_path"] = str(audio_path)
        project.reference_audio_path = str(audio_path)

    if (
        previous_tts_engine != normalized_tts_engine
        or previous_reference_audio_text != normalized_reference_audio_text
        or previous_cosyvoice_speed != normalized_cosyvoice_speed
        or previous_voice_profile_id != str(config.get("voice_profile_id") or "")
    ):
        if _reset_tts_segments(session, project.id):
            project.status = "segmented"

    if previous_segmentation_mode != resolved_segmentation_mode:
        for segment in session.exec(
            select(Segment).where(Segment.project_id == project.id)
        ).all():
            session.delete(segment)
        if project.script_clean_path:
            project.status = "script_imported"

    project.name = project_name
    project.output_dir = str(output_directory)
    project.config_json = json.dumps(config, ensure_ascii=False)
    ensure_project_dirs(get_project_work_dir(project, get_settings().workspace_dir))
    project.updated_at = utc_now_iso()
    session.add(project)
    session.commit()
    session.refresh(project)
    write_project_descriptor(project)
    return project


def ensure_output_filename(session: Session, project: Project) -> Project:
    config = load_project_config(project)
    if str(config.get("output_filename") or "").strip():
        return project
    config["output_filename"] = safe_filename_stem(project.name or _timestamp_stem())
    project.config_json = json.dumps(config, ensure_ascii=False)
    project.updated_at = utc_now_iso()
    ensure_project_dirs(get_project_work_dir(project, get_settings().workspace_dir))
    session.add(project)
    session.commit()
    session.refresh(project)
    write_project_descriptor(project)
    return project


def _reset_tts_segments(session: Session, project_id: str) -> bool:
    reset_any = False
    for segment in session.exec(select(Segment).where(Segment.project_id == project_id)).all():
        reset_any = True
        segment.audio_path = None
        segment.duration = None
        segment.start_time = None
        segment.end_time = None
        segment.status = "pending"
        segment.error_message = None
        segment.updated_at = utc_now_iso()
        session.add(segment)
    return reset_any


def _timestamp_stem() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _available_project_directory_name(output_root: Path, project_name: str, project_id: str) -> str:
    base = safe_filename_stem(project_name or project_id)
    candidate = base
    suffix = 2
    while (output_root / candidate).exists():
        candidate = safe_filename_stem(f"{base}-{suffix}")
        suffix += 1
    return candidate
