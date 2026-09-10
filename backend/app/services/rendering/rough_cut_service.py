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

from app.config import StoryboardTransitionEffect, get_settings
from app.models.project import Project
from app.infrastructure.ffmpeg import probe_duration, probe_media, run_ffmpeg
from app.infrastructure.project_layout import (
    ensure_project_dirs,
    get_final_audio_path,
    get_final_video_path,
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
MIN_TRANSITION_DURATION_SECONDS = 0.2
PROGRESS_WRITE_RETRIES = 5
_composing_project_ids: set[str] = set()
_composing_projects_lock = threading.Lock()


@dataclass
class SelectedVideo:
    source_path: Path
    title_group: str
    source_duration: float
    clip_duration: float


@dataclass(frozen=True)
class PlannedTransition:
    # One-based index of the clip immediately before this transition.
    after_clip_index: int
    effect: str
    duration: float


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
            raise VideoCompositionRunningError(
                "Video composition is already running for this project"
            )
        _composing_project_ids.add(project.id)

    try:
        return _compose_video(session, project)
    finally:
        with _composing_projects_lock:
            _composing_project_ids.discard(project.id)


def _compose_video(session: Session, project: Project) -> Path:
    settings = get_settings()
    base_dir = get_project_work_dir(project, settings.workspace_dir)
    ensure_project_dirs(base_dir)
    video_dir = base_dir / "video"
    temp_dir = video_dir / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    progress_path = video_dir / "progress.json"
    write_video_progress(
        progress_path, "running", "scanning", 5, message="Scanning video materials"
    )

    project.status = "video_composing"
    project.updated_at = datetime.utcnow().isoformat()
    session.add(project)
    session.commit()

    write_video_progress(
        progress_path, "running", "selecting", 12, message="Selecting video materials"
    )
    selected, transition_plan, target_duration = prepare_rough_cut_selection(project)

    write_video_progress(
        progress_path,
        "running",
        "normalizing",
        15,
        total=len(selected),
        message="Normalizing selected clips",
    )
    temp_paths = normalize_selected_clips(selected, temp_dir, progress_path, project.id)
    normalized_durations = [probe_duration(path) for path in temp_paths]
    concat_path = video_dir / "concat.txt"
    concat_path.write_text(
        "\n".join(f"file '{path.as_posix()}'" for path in temp_paths),
        encoding="utf-8",
    )

    filter_script_path = video_dir / "transition_filter.txt"
    output_path = get_final_video_path(project, settings.workspace_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_video_progress(
        progress_path,
        "running",
        "transitioning" if transition_plan else "concatenating",
        95,
        total=len(selected),
        completed=len(selected),
        message=(
            f"Applying {len(transition_plan)} video transitions"
            if transition_plan
            else "Concatenating final video"
        ),
    )
    compose_normalized_clips(
        temp_paths,
        normalized_durations,
        concat_path,
        filter_script_path,
        transition_plan,
        output_path,
        project_id=project.id,
    )
    video_duration = probe_duration(output_path)
    if video_duration <= target_duration:
        # Frame-rate normalization and imperfect source tails can make the
        # encoded result slightly shorter than the probed source durations.
        # Retry with the measured deficit plus one frame instead of failing a
        # long-running batch at the final validation step.
        retry_padding = VIDEO_TAIL_PADDING + (target_duration - video_duration) + (1 / TARGET_FPS)
        logger.warning(
            "Generated video is %.3fs shorter than audio; retrying with %.3fs tail padding",
            target_duration - video_duration,
            retry_padding,
        )
        compose_normalized_clips(
            temp_paths,
            normalized_durations,
            concat_path,
            filter_script_path,
            transition_plan,
            output_path,
            retry_padding,
            project.id,
        )
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


def prepare_rough_cut_selection(
    project: Project,
) -> tuple[list[SelectedVideo], list[PlannedTransition], float]:
    """Select the rough-cut source clips without rendering them."""
    settings = get_settings()
    config = _load_project_config(project)
    media_dir_value = str(config.get("media_video_dir") or "").strip()
    if not media_dir_value:
        raise ValueError("Video material directory is not configured")
    media_dir = Path(media_dir_value).expanduser().resolve()
    if not media_dir.is_dir():
        raise ValueError("Video material directory does not exist")

    audio_path = get_final_audio_path(project, settings.workspace_dir)
    if not audio_path.is_file():
        raise ValueError("Final WAV audio does not exist; merge audio before composing video")
    target_duration = probe_duration(audio_path)
    if target_duration <= 0:
        raise ValueError("Final WAV audio duration is invalid")

    source_paths = list_rough_cut_video_files(media_dir)
    grouped_paths = group_video_files(source_paths)
    transitions_enabled = bool(config.get("storyboard_transition_enabled", True))
    enabled_effects = (
        [item for item in settings.storyboard_transition_effects if item.enabled]
        if transitions_enabled
        else []
    )
    transition_duration = settings.storyboard_transition_duration_seconds
    selected = select_videos_for_duration(
        grouped_paths,
        target_duration,
        transition_duration if enabled_effects else 0.0,
    )
    transition_plan = build_transition_plan(
        selected,
        enabled_effects,
        group_min_clips=settings.storyboard_transition_group_min_clips,
        group_max_clips=settings.storyboard_transition_group_max_clips,
        min_per_group=settings.storyboard_transition_min_per_group,
        max_per_group=settings.storyboard_transition_max_per_group,
        duration=transition_duration,
    )
    base_dir = get_project_work_dir(project, settings.workspace_dir)
    ensure_project_dirs(base_dir)
    write_selected_manifest(
        base_dir / "video" / "selected_videos.json",
        selected,
        target_duration,
        transition_plan,
    )
    return selected, transition_plan, target_duration


def compose_normalized_clips(
    clip_paths: list[Path],
    clip_durations: list[float],
    concat_path: Path,
    filter_script_path: Path,
    transition_plan: list[PlannedTransition],
    output_path: Path,
    tail_padding: float = VIDEO_TAIL_PADDING,
    project_id: str | None = None,
    output_duration: float | None = None,
) -> None:
    if transition_plan:
        concatenate_clips_with_transitions(
            clip_paths,
            clip_durations,
            filter_script_path,
            transition_plan,
            output_path,
            tail_padding,
            project_id,
            output_duration,
        )
        return
    concatenate_normalized_clips(
        concat_path,
        output_path,
        tail_padding,
        project_id,
        output_duration,
    )


def concatenate_clips_with_transitions(
    clip_paths: list[Path],
    clip_durations: list[float],
    filter_script_path: Path,
    transition_plan: list[PlannedTransition],
    output_path: Path,
    tail_padding: float = VIDEO_TAIL_PADDING,
    project_id: str | None = None,
    output_duration: float | None = None,
) -> None:
    if len(clip_paths) != len(clip_durations):
        raise ValueError("Clip paths and durations must have the same length")
    if len(clip_paths) < 2:
        raise ValueError("At least two clips are required for video transitions")

    filter_script_path.parent.mkdir(parents=True, exist_ok=True)
    filter_script_path.write_text(
        build_transition_filter(clip_durations, transition_plan, tail_padding),
        encoding="utf-8",
    )
    args = ["-y"]
    for path in clip_paths:
        args.extend(["-i", str(path)])
    args.extend(
        [
            "-filter_complex_script",
            str(filter_script_path),
            "-map",
            "[vout]",
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
        ]
    )
    if output_duration is not None:
        args.extend(["-t", f"{output_duration:.3f}"])
    args.append(str(output_path))
    run_ffmpeg(args, project_id)


def build_transition_filter(
    clip_durations: list[float],
    transition_plan: list[PlannedTransition],
    tail_padding: float = VIDEO_TAIL_PADDING,
) -> str:
    if len(clip_durations) < 2:
        raise ValueError("At least two clip durations are required")
    transitions = {item.after_clip_index: item for item in transition_plan}
    if len(transitions) != len(transition_plan):
        raise ValueError("Only one transition can be assigned to a video boundary")

    filters = [
        f"[{index}:v]settb=AVTB,setpts=PTS-STARTPTS,setsar=1[v{index}]"
        for index in range(len(clip_durations))
    ]
    current_label = "v0"
    current_duration = clip_durations[0]
    for clip_index in range(1, len(clip_durations)):
        output_label = f"join{clip_index}"
        transition = transitions.get(clip_index)
        if transition:
            duration = _resolve_transition_duration(
                transition.duration,
                current_duration,
                clip_durations[clip_index],
            )
            if duration >= MIN_TRANSITION_DURATION_SECONDS:
                offset = max(0.0, current_duration - duration)
                filters.append(
                    f"[{current_label}][v{clip_index}]xfade=transition={transition.effect}:"
                    f"duration={duration:.3f}:offset={offset:.3f}[{output_label}]"
                )
                current_duration += clip_durations[clip_index] - duration
                current_label = output_label
                continue
        filters.append(f"[{current_label}][v{clip_index}]concat=n=2:v=1:a=0[{output_label}]")
        current_duration += clip_durations[clip_index]
        current_label = output_label

    filters.append(
        f"[{current_label}]tpad=stop_mode=clone:stop_duration={tail_padding:.3f},"
        f"fps={TARGET_FPS},setsar=1,format=yuv420p,setparams=range=tv[vout]"
    )
    return ";\n".join(filters)


def concatenate_normalized_clips(
    concat_path: Path,
    output_path: Path,
    tail_padding: float = VIDEO_TAIL_PADDING,
    project_id: str | None = None,
    output_duration: float | None = None,
) -> None:
    # Re-encode the joined stream so every boundary gets a clean timestamp and
    # reference-frame chain. Stream copying can produce a one-frame flash on
    # some hardware decoders even when all input clips use H.264.
    args = [
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
        f"tpad=stop_mode=clone:stop_duration={tail_padding:.3f},"
        f"setsar=1,format=yuv420p,setparams=range=tv",
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
    ]
    if output_duration is not None:
        args.extend(["-t", f"{output_duration:.3f}"])
    args.append(str(output_path))
    run_ffmpeg(args, project_id)


def scan_video_files(media_dir: Path) -> list[Path]:
    paths = [
        path
        for path in media_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    ]
    if not paths:
        raise ValueError("No supported video files found in material directory")
    return sorted(paths, key=lambda item: str(item).lower())


def list_rough_cut_video_files(media_dir: Path) -> list[Path]:
    """Scan the configured landscape directory without importing it into the library."""
    return scan_video_files(media_dir.resolve())


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


def build_transition_plan(
    selected: list[SelectedVideo],
    effects: list[StoryboardTransitionEffect],
    *,
    group_min_clips: int = 2,
    group_max_clips: int = 5,
    min_per_group: int = 1,
    max_per_group: int = 2,
    duration: float = 0.45,
) -> list[PlannedTransition]:
    return build_transition_plan_for_durations(
        [item.clip_duration for item in selected],
        effects,
        group_min_clips=group_min_clips,
        group_max_clips=group_max_clips,
        min_per_group=min_per_group,
        max_per_group=max_per_group,
        duration=duration,
    )


def build_full_transition_plan(
    selected: list[SelectedVideo],
    effects: list[StoryboardTransitionEffect],
    duration: float = 0.45,
) -> list[PlannedTransition]:
    """Add one configured transition at every usable clip boundary."""
    enabled = [item for item in effects if item.enabled and item.percentage > 0]
    if len(selected) < 2 or not enabled:
        return []

    effect_names = [item.name for item in enabled]
    effect_weights = [item.percentage for item in enabled]
    plan = []
    for boundary in range(1, len(selected)):
        resolved_duration = _resolve_transition_duration(
            duration,
            selected[boundary - 1].clip_duration,
            selected[boundary].clip_duration,
        )
        if resolved_duration < MIN_TRANSITION_DURATION_SECONDS:
            continue
        plan.append(
            PlannedTransition(
                boundary,
                random.choices(effect_names, weights=effect_weights, k=1)[0],
                resolved_duration,
            )
        )
    return plan


def build_transition_plan_for_durations(
    clip_durations: list[float],
    effects: list[StoryboardTransitionEffect],
    *,
    group_min_clips: int = 2,
    group_max_clips: int = 5,
    min_per_group: int = 1,
    max_per_group: int = 2,
    duration: float = 0.45,
) -> list[PlannedTransition]:
    enabled = [item for item in effects if item.enabled and item.percentage > 0]
    if len(clip_durations) < 2 or not enabled or max_per_group == 0:
        return []

    effect_names = [item.name for item in enabled]
    effect_weights = [item.percentage for item in enabled]
    plan: list[PlannedTransition] = []
    group_start = 0
    while group_start < len(clip_durations) - 1:
        group_end = min(
            len(clip_durations),
            group_start + random.randint(group_min_clips, group_max_clips),
        )
        candidates: list[tuple[int, float]] = []
        for boundary in range(group_start + 1, group_end):
            resolved_duration = _resolve_transition_duration(
                duration,
                clip_durations[boundary - 1],
                clip_durations[boundary],
            )
            if resolved_duration >= MIN_TRANSITION_DURATION_SECONDS:
                candidates.append((boundary, resolved_duration))
        if candidates:
            lower = min(min_per_group, len(candidates))
            upper = min(max_per_group, len(candidates))
            count = random.randint(lower, upper) if upper else 0
            for boundary, resolved_duration in sorted(random.sample(candidates, count)):
                effect = random.choices(effect_names, weights=effect_weights, k=1)[0]
                # Candidates are sampled without replacement, so a scene boundary
                # can receive at most one transition effect.
                plan.append(PlannedTransition(boundary, effect, resolved_duration))
        group_start = group_end
    return plan


def _resolve_transition_duration(requested: float, before: float, after: float) -> float:
    return max(0.0, min(requested, before / 3, after / 3))


def select_videos_for_duration(
    groups: dict[str, list[Path]],
    target_duration: float,
    maximum_boundary_overlap: float = 0.0,
) -> list[SelectedVideo]:
    if maximum_boundary_overlap < 0:
        raise ValueError("Maximum transition overlap cannot be negative")
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
        minimum_effective_duration = total - maximum_boundary_overlap * max(0, len(selected) - 1)
        if minimum_effective_duration > target_duration:
            return selected

    if not selected:
        raise ValueError("No readable video files found in material directory")
    raise ValueError(
        f"Not enough unique video title groups to cover target duration: "
        f"{total:.2f}s selected before transitions, {target_duration:.2f}s required"
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
            f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}:"
            f"force_original_aspect_ratio=increase:out_range=tv,"
            f"crop={TARGET_WIDTH}:{TARGET_HEIGHT},"
            f"fps={TARGET_FPS},setsar=1,format=yuv420p,setparams=range=tv"
        )
        run_ffmpeg(
            [
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
            ],
            project_id,
        )
        _validate_normalized_clip(output_path, item.source_path)
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


def _validate_normalized_clip(output_path: Path, source_path: Path) -> None:
    metadata = probe_media(output_path)
    issues = []
    if metadata.get("width") != TARGET_WIDTH or metadata.get("height") != TARGET_HEIGHT:
        issues.append(f"size={metadata.get('width')}x{metadata.get('height')}")
    if metadata.get("sample_aspect_ratio") not in {"1:1", "1/1"}:
        issues.append(f"SAR={metadata.get('sample_aspect_ratio')}")
    frame_rate = metadata.get("frame_rate_value")
    if frame_rate is None or abs(float(frame_rate) - TARGET_FPS) > 0.01:
        issues.append(f"fps={frame_rate}")
    if metadata.get("pixel_format") != "yuv420p":
        issues.append(f"pixel_format={metadata.get('pixel_format')}")
    if metadata.get("audio_stream_count"):
        issues.append(f"audio_streams={metadata.get('audio_stream_count')}")
    if issues:
        raise RuntimeError(
            f"Normalized clip is incompatible with final composition: "
            f"{output_path.name} from {source_path} ({', '.join(issues)})"
        )


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


def write_selected_manifest(
    path: Path,
    selected: list[SelectedVideo],
    target_duration: float,
    transition_plan: list[PlannedTransition] | None = None,
) -> None:
    transition_plan = transition_plan or []
    transitions_by_boundary = {item.after_clip_index: item for item in transition_plan}
    transition_overlap = sum(item.duration for item in transition_plan)
    selected_duration = sum(item.clip_duration for item in selected)
    data = {
        "target_duration": target_duration,
        "selected_duration": selected_duration,
        "transition_overlap_duration": transition_overlap,
        "effective_selected_duration": selected_duration - transition_overlap,
        "selection_mode": "landscape_rough_cut",
        "source_type": "configured_landscape_directory",
        "transitions": [
            {
                "after_clip_index": item.after_clip_index,
                "effect": item.effect,
                "duration": item.duration,
            }
            for item in transition_plan
        ],
        "items": [
            {
                "title_group": item.title_group,
                "source_path": str(item.source_path),
                "source_duration": item.source_duration,
                "clip_duration": item.clip_duration,
                "transition_to_next": (
                    {
                        "effect": transitions_by_boundary[index].effect,
                        "duration": transitions_by_boundary[index].duration,
                    }
                    if index in transitions_by_boundary
                    else None
                ),
            }
            for index, item in enumerate(selected, start=1)
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
