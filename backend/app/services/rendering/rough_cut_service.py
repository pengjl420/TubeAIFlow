import json
import logging
import random
import re
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlmodel import Session

from app.config import get_settings
from app.models.project import Project
from app.infrastructure.ffmpeg import probe_duration, run_ffmpeg
from app.infrastructure.project_layout import (
    ensure_project_dirs,
    get_final_audio_path,
    get_final_video_path,
    get_output_stem,
    get_project_work_dir,
)


logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".m4v", ".mpg", ".mpeg"}
TARGET_WIDTH = 1920
TARGET_HEIGHT = 1080
TARGET_FPS = 30
# Source videos occasionally contain an undecodable or placeholder first frame.
# Skipping a few frames also prevents that frame from becoming a clip boundary.
CLIP_START_OFFSET = 0.1
VIDEO_TAIL_PADDING = 0.5
PROGRESS_WRITE_RETRIES = 5
_composing_project_ids: set[str] = set()
_composing_projects_lock = threading.Lock()


@dataclass
class SelectedVideo:
    source_path: Path
    title_group: str
    source_duration: float
    clip_duration: float


class VideoCompositionRunningError(ValueError):
    pass


def save_video_settings(session: Session, project: Project, media_video_dir: str) -> Project:
    directory = Path(media_video_dir).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError("Video material directory does not exist")

    config = _load_project_config(project)
    config["media_video_dir"] = str(directory)
    project.config_json = json.dumps(config, ensure_ascii=False)
    project.updated_at = datetime.utcnow().isoformat()
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def compose_video(session: Session, project: Project) -> Path:
    with _composing_projects_lock:
        if project.id in _composing_project_ids:
            raise VideoCompositionRunningError("Video composition is already running for this project")
        _composing_project_ids.add(project.id)

    try:
        return _compose_video(session, project)
    finally:
        with _composing_projects_lock:
            _composing_project_ids.discard(project.id)


def _compose_video(session: Session, project: Project) -> Path:
    config = _load_project_config(project)
    media_dir_value = str(config.get("media_video_dir") or "").strip()
    if not media_dir_value:
        raise ValueError("Video material directory is not configured")

    media_dir = Path(media_dir_value).expanduser().resolve()
    if not media_dir.is_dir():
        raise ValueError("Video material directory does not exist")

    audio_path = get_final_audio_path(project, get_settings().workspace_dir)
    if not audio_path.is_file():
        raise ValueError("Final WAV audio does not exist; merge audio before composing video")

    target_duration = probe_duration(audio_path)
    if target_duration <= 0:
        raise ValueError("Final WAV audio duration is invalid")

    base_dir = get_project_work_dir(project, get_settings().workspace_dir)
    ensure_project_dirs(base_dir)
    video_dir = base_dir / "video"
    temp_dir = video_dir / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    progress_path = video_dir / "progress.json"
    write_video_progress(progress_path, "running", "scanning", 5, message="Scanning video materials")

    project.status = "video_composing"
    project.updated_at = datetime.utcnow().isoformat()
    session.add(project)
    session.commit()

    source_paths = scan_video_files(media_dir)
    write_video_progress(progress_path, "running", "selecting", 12, message="Selecting video materials")
    grouped_paths = group_video_files(source_paths)
    selected = select_videos_for_duration(grouped_paths, target_duration)
    write_selected_manifest(video_dir / "selected_videos.json", selected, target_duration)

    write_video_progress(
        progress_path,
        "running",
        "normalizing",
        15,
        total=len(selected),
        message="Normalizing selected clips",
    )
    temp_paths = normalize_selected_clips(selected, temp_dir, progress_path, project.id)
    concat_path = video_dir / "concat.txt"
    concat_path.write_text(
        "\n".join(f"file '{path.as_posix()}'" for path in temp_paths),
        encoding="utf-8",
    )

    output_path = get_final_video_path(project, get_settings().workspace_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_video_progress(
        progress_path,
        "running",
        "concatenating",
        95,
        total=len(selected),
        completed=len(selected),
        message="Concatenating final video",
    )
    concatenate_normalized_clips(concat_path, output_path, project_id=project.id)
    video_duration = probe_duration(output_path)
    if video_duration <= target_duration:
        # Frame-rate normalization and imperfect source tails can make the
        # encoded result slightly shorter than the probed source durations.
        # Retry with the measured deficit plus one frame instead of failing a
        # long-running batch at the final validation step.
        retry_padding = (
            VIDEO_TAIL_PADDING
            + (target_duration - video_duration)
            + (1 / TARGET_FPS)
        )
        logger.warning(
            "Generated video is %.3fs shorter than audio; retrying with %.3fs tail padding",
            target_duration - video_duration,
            retry_padding,
        )
        concatenate_normalized_clips(concat_path, output_path, retry_padding, project.id)
        video_duration = probe_duration(output_path)
    if video_duration <= target_duration:
        raise RuntimeError(
            f"Generated video is not longer than audio: "
            f"video={video_duration:.3f}s, audio={target_duration:.3f}s"
        )

    project.status = "video_completed"
    project.updated_at = datetime.utcnow().isoformat()
    session.add(project)
    session.commit()
    write_video_progress(
        progress_path,
        "completed",
        "completed",
        100,
        total=len(selected),
        completed=len(selected),
        message="Video generation completed",
    )
    return output_path


def concatenate_normalized_clips(
    concat_path: Path,
    output_path: Path,
    tail_padding: float = VIDEO_TAIL_PADDING,
    project_id: str | None = None,
) -> None:
    # Re-encode the joined stream so every boundary gets a clean timestamp and
    # reference-frame chain. Stream copying can produce a one-frame flash on
    # some hardware decoders even when all input clips use H.264.
    run_ffmpeg([
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        "-map",
        "0:v:0",
        "-vf",
        f"tpad=stop_mode=clone:stop_duration={tail_padding:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(TARGET_FPS),
        "-an",
        "-movflags",
        "+faststart",
        str(output_path),
    ], project_id)


def scan_video_files(media_dir: Path) -> list[Path]:
    paths = [
        path
        for path in media_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    ]
    if not paths:
        raise ValueError("No supported video files found in material directory")
    return sorted(paths, key=lambda item: str(item).lower())


def group_video_files(paths: list[Path]) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = {}
    for path in paths:
        title = normalize_video_title(path)
        groups.setdefault(title, []).append(path)
    return groups


def normalize_video_title(path: Path) -> str:
    title = path.stem.strip()
    title = re.sub(r"\s*[（(]\d+[）)]\s*$", "", title)
    title = re.sub(r"[\s_-]+\d+\s*$", "", title)
    return title.strip() or path.stem.strip()


def select_videos_for_duration(groups: dict[str, list[Path]], target_duration: float) -> list[SelectedVideo]:
    group_items = list(groups.items())
    random.shuffle(group_items)

    selected: list[SelectedVideo] = []
    total = 0.0
    for title_group, paths in group_items:
        path = random.choice(paths)
        try:
            duration = probe_duration(path)
        except RuntimeError as exc:
            logger.warning("Skip video with unreadable duration %s: %s", path, exc)
            continue
        if duration <= 0:
            continue

        usable_duration = duration - CLIP_START_OFFSET
        if usable_duration <= 0:
            continue

        # This is a rough-cut composition. Keep the final selected material in
        # full instead of trimming it to the exact remaining audio duration.
        clip_duration = usable_duration
        selected.append(SelectedVideo(path, title_group, duration, clip_duration))
        total += clip_duration
        if total > target_duration:
            return selected

    if not selected:
        raise ValueError("No readable video files found in material directory")
    raise ValueError(
        f"Not enough unique video title groups to cover target duration: "
        f"{total:.2f}s selected, {target_duration:.2f}s required"
    )


def normalize_selected_clips(
    selected: list[SelectedVideo],
    temp_dir: Path,
    progress_path: Path | None = None,
    project_id: str | None = None,
) -> list[Path]:
    temp_paths: list[Path] = []
    for index, item in enumerate(selected, start=1):
        if progress_path:
            percent = 15 + int((index - 1) / len(selected) * 75)
            write_video_progress(
                progress_path,
                "running",
                "normalizing",
                percent,
                total=len(selected),
                completed=index - 1,
                current_file=item.source_path.name,
                message=f"Normalizing clip {index} of {len(selected)}",
            )
        output_path = temp_dir / f"{index:04d}.mp4"
        output_path.unlink(missing_ok=True)
        vf = (
            f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={TARGET_WIDTH}:{TARGET_HEIGHT},"
            f"fps={TARGET_FPS},format=yuv420p"
        )
        run_ffmpeg([
            "-y",
            "-i",
            str(item.source_path),
            "-ss",
            f"{CLIP_START_OFFSET:.3f}",
            "-t",
            f"{item.clip_duration:.3f}",
            "-vf",
            vf,
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-movflags",
            "+faststart",
            str(output_path),
        ], project_id)
        temp_paths.append(output_path)
        if progress_path:
            write_video_progress(
                progress_path,
                "running",
                "normalizing",
                15 + int(index / len(selected) * 75),
                total=len(selected),
                completed=index,
                current_file=item.source_path.name,
                message=f"Normalized clip {index} of {len(selected)}",
            )
    return temp_paths


def write_video_progress(
    path: Path,
    status: str,
    stage: str,
    percent: int,
    *,
    total: int = 0,
    completed: int = 0,
    current_file: str | None = None,
    message: str = "",
    error: str | None = None,
) -> None:
    data = {
        "status": status,
        "stage": stage,
        "percent": max(0, min(percent, 100)),
        "total": total,
        "completed": completed,
        "current_file": current_file,
        "message": message,
        "error": error,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    # A unique temporary name prevents concurrent writers from opening the
    # same file. Windows will reject os.replace while either file is briefly
    # held by another process, so retry that transient failure.
    temp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        for attempt in range(PROGRESS_WRITE_RETRIES):
            try:
                temp_path.replace(path)
                break
            except PermissionError:
                if attempt == PROGRESS_WRITE_RETRIES - 1:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        temp_path.unlink(missing_ok=True)


def read_video_progress(project: Project) -> dict | None:
    path = get_project_work_dir(project, get_settings().workspace_dir) / "video" / "progress.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def mark_video_progress_failed(project: Project, error: str) -> None:
    path = get_project_work_dir(project, get_settings().workspace_dir) / "video" / "progress.json"
    previous = read_video_progress(project) or {}
    write_video_progress(
        path,
        "failed",
        "failed",
        int(previous.get("percent", 0)),
        total=int(previous.get("total", 0)),
        completed=int(previous.get("completed", 0)),
        current_file=previous.get("current_file"),
        message="Video generation failed",
        error=error,
    )


def write_selected_manifest(path: Path, selected: list[SelectedVideo], target_duration: float) -> None:
    data = {
        "target_duration": target_duration,
        "selected_duration": sum(item.clip_duration for item in selected),
        "items": [
            {
                "title_group": item.title_group,
                "source_path": str(item.source_path),
                "source_duration": item.source_duration,
                "clip_duration": item.clip_duration,
            }
            for item in selected
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_project_config(project: Project) -> dict:
    if not project.config_json:
        return {}
    try:
        data = json.loads(project.config_json)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
