import logging
import os
import uuid
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

from app.config import get_settings
from app.models.project import Project
from app.models.narration import Segment
from app.infrastructure.ffmpeg import probe_duration, run_ffmpeg
from app.infrastructure.project_layout import ensure_project_dirs, get_final_audio_path, get_project_work_dir


logger = logging.getLogger(__name__)


def update_segment_durations(session: Session, project: Project) -> list[Segment]:
    segments = session.exec(
        select(Segment)
        .where(Segment.project_id == project.id)
        .order_by(Segment.segment_index)
    ).all()
    for segment in segments:
        if not segment.audio_path:
            continue
        segment.duration = probe_duration(Path(segment.audio_path))
        session.add(segment)
    session.commit()
    return list(segments)


def merge_project_audio(session: Session, project: Project) -> Path:
    segments = session.exec(
        select(Segment)
        .where(Segment.project_id == project.id)
        .order_by(Segment.segment_index)
    ).all()
    if not segments:
        raise ValueError("Project has no segments to merge")

    missing = [
        segment.segment_id
        for segment in segments
        if not segment.audio_path or not Path(segment.audio_path).is_file()
    ]
    if missing:
        preview = ", ".join(missing[:10])
        suffix = "..." if len(missing) > 10 else ""
        raise ValueError(f"Segment audio is missing: {preview}{suffix}")

    audio_segments = list(segments)
    audio_paths = [Path(segment.audio_path) for segment in audio_segments]
    if not audio_paths:
        raise ValueError("No segment audio files to merge")

    base_dir = get_project_work_dir(project, get_settings().workspace_dir)
    ensure_project_dirs(base_dir)
    list_path = base_dir / "audio" / "segments.txt"
    full_voice_path = get_final_audio_path(project, get_settings().workspace_dir)
    full_voice_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = full_voice_path.with_name(
        f".{full_voice_path.stem}.{uuid.uuid4().hex}.tmp{full_voice_path.suffix}"
    )
    try:
        list_path.write_text(
            "\n".join(f"file '{path.as_posix()}'" for path in audio_paths),
            encoding="utf-8",
        )
    except OSError as exc:
        raise RuntimeError(f"Cannot write FFmpeg concat list: {list_path}") from exc
    try:
        run_ffmpeg(
            ["-y", "-f", "concat", "-safe", "0", "-i", str(list_path), "-c", "copy", str(temporary_path)],
            project.id,
        )
        if not temporary_path.is_file():
            raise RuntimeError("FFmpeg did not create the merged audio file")
        os.replace(temporary_path, full_voice_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    for segment in audio_segments:
        if segment.duration is None:
            segment.duration = probe_duration(Path(segment.audio_path))
            session.add(segment)
    project.status = "audio_merged"
    project.updated_at = datetime.utcnow().isoformat()
    session.add(project)
    session.commit()
    return full_voice_path
