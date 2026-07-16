import json
import uuid
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

from app.config import get_settings
from app.models.project import Project
from app.models.segment import Segment
from app.services.segmenter import split_script
from app.services.text_cleaner import clean_script
from app.utils.file_utils import ensure_inside_any, project_dir
from app.utils.project_paths import (
    ensure_project_dirs,
    get_output_stem,
    get_project_work_dir,
    load_project_config,
    safe_filename_stem,
)
from app.utils.time_utils import utc_now_iso


SUPPORTED_TTS_ENGINES = {"index_tts", "qwen3_tts"}


def create_project(session: Session, name: str, config: dict | None = None) -> Project:
    settings = get_settings()
    project_id = uuid.uuid4().hex[:12]
    output_dir = project_dir(settings.workspace_dir, project_id)
    project = Project(
        id=project_id,
        name=name,
        output_dir=str(output_dir),
        status="created",
        config_json=json.dumps(config or {}, ensure_ascii=False),
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def list_projects(session: Session) -> list[Project]:
    return list(session.exec(select(Project).order_by(Project.created_at.desc())).all())


def get_project(session: Session, project_id: str) -> Project | None:
    return session.get(Project, project_id)


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
    return project


def create_segments(session: Session, project: Project) -> list[Segment]:
    if not project.script_clean_path:
        raise ValueError("Project has no cleaned script")
    settings = get_settings()
    clean_path = ensure_inside_any(
        Path(project.script_clean_path),
        [get_project_work_dir(project, settings.workspace_dir), project_dir(settings.workspace_dir, project.id)],
    )
    if not clean_path.is_file():
        raise ValueError("Cleaned script file does not exist")
    clean_text = clean_path.read_text(encoding="utf-8")
    segment_data = split_script(clean_text)
    if not segment_data:
        raise ValueError("Cleaned script is empty")

    existing = session.exec(select(Segment).where(Segment.project_id == project.id)).all()
    segments = [
        Segment(
            id=f"{project.id}_{item['segment_id']}",
            segment_id=item["segment_id"],
            project_id=project.id,
            segment_index=item["index"],
            text_zh=item["text_zh"],
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
    config["output_filename"] = safe_filename_stem(output_filename or project.name or _timestamp_stem())
    project.output_dir = str(directory)
    project.config_json = json.dumps(config, ensure_ascii=False)
    ensure_project_dirs(get_project_work_dir(project, get_settings().workspace_dir))
    project.updated_at = utc_now_iso()
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def update_project_settings(
    session: Session,
    project: Project,
    name: str,
    output_dir: str,
    output_filename: str,
    media_video_dir: str,
    tts_engine: str = "index_tts",
    reference_audio_text: str = "",
    include_translation: bool = False,
    include_video: bool = False,
) -> Project:
    project_name = name.strip()
    if not project_name:
        raise ValueError("Project name is required")
    if not output_dir.strip():
        raise ValueError("Output directory is required")
    normalized_tts_engine = tts_engine.strip().lower()
    if normalized_tts_engine not in SUPPORTED_TTS_ENGINES:
        raise ValueError("Unsupported TTS engine")

    video_directory: Path | None = None
    if include_video and not media_video_dir.strip():
        raise ValueError("Video material directory is required when video generation is enabled")
    if media_video_dir.strip():
        video_directory = Path(media_video_dir).expanduser().resolve()
        if not video_directory.is_dir():
            raise ValueError("Video material directory does not exist")

    output_directory = Path(output_dir).expanduser().resolve()
    output_directory.mkdir(parents=True, exist_ok=True)

    config = load_project_config(project)
    previous_tts_engine = str(config.get("tts_engine") or "index_tts").strip().lower()
    previous_reference_audio_text = str(config.get("reference_audio_text") or "").strip()
    config["output_filename"] = safe_filename_stem(output_filename or project_name or _timestamp_stem())
    config["tts_engine"] = normalized_tts_engine
    config["reference_audio_text"] = reference_audio_text.strip()
    config["include_translation"] = include_translation
    config["include_video"] = include_video
    if video_directory:
        config["media_video_dir"] = str(video_directory)
    else:
        config.pop("media_video_dir", None)

    if (
        previous_tts_engine != normalized_tts_engine
        or previous_reference_audio_text != reference_audio_text.strip()
    ):
        if _reset_tts_segments(session, project.id):
            project.status = "segmented"

    project.name = project_name
    project.output_dir = str(output_directory)
    project.config_json = json.dumps(config, ensure_ascii=False)
    ensure_project_dirs(get_project_work_dir(project, get_settings().workspace_dir))
    project.updated_at = utc_now_iso()
    session.add(project)
    session.commit()
    session.refresh(project)
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
