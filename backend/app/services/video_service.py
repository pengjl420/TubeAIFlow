import json
import logging
import random
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlmodel import Session

from app.config import get_settings
from app.models.project import Project
from app.utils.ffmpeg_utils import probe_duration, run_ffmpeg
from app.utils.project_paths import (
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


@dataclass
class SelectedVideo:
    source_path: Path
    title_group: str
    source_duration: float
    clip_duration: float


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


def compose_silent_video(session: Session, project: Project) -> Path:
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

    project.status = "video_composing"
    project.updated_at = datetime.utcnow().isoformat()
    session.add(project)
    session.commit()

    source_paths = scan_video_files(media_dir)
    grouped_paths = group_video_files(source_paths)
    selected = select_videos_for_duration(grouped_paths, target_duration)
    write_selected_manifest(video_dir / "selected_videos.json", selected, target_duration)

    temp_paths = normalize_selected_clips(selected, temp_dir)
    concat_path = video_dir / "concat.txt"
    concat_path.write_text(
        "\n".join(f"file '{path.as_posix()}'" for path in temp_paths),
        encoding="utf-8",
    )

    output_path = get_final_video_path(project, get_settings().workspace_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg([
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        "-an",
        "-c",
        "copy",
        str(output_path),
    ])

    project.status = "video_completed"
    project.updated_at = datetime.utcnow().isoformat()
    session.add(project)
    session.commit()
    return output_path


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
    errors: list[str] = []

    for title_group, paths in group_items:
        path = random.choice(paths)
        try:
            duration = probe_duration(path)
        except RuntimeError as exc:
            logger.warning("Skip video with unreadable duration %s: %s", path, exc)
            errors.append(f"{path}: {exc}")
            continue
        if duration <= 0:
            continue

        remaining = target_duration - total
        clip_duration = min(duration, remaining)
        selected.append(SelectedVideo(path, title_group, duration, clip_duration))
        total += clip_duration
        if total >= target_duration:
            return selected

    if not selected:
        raise ValueError("No readable video files found in material directory")
    raise ValueError(
        f"Not enough unique video title groups to cover target duration: "
        f"{total:.2f}s selected, {target_duration:.2f}s required"
    )


def normalize_selected_clips(selected: list[SelectedVideo], temp_dir: Path) -> list[Path]:
    temp_paths: list[Path] = []
    for index, item in enumerate(selected, start=1):
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
        ])
        temp_paths.append(output_path)
    return temp_paths


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
