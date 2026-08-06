import json
import tempfile
from pathlib import Path

from app.config import get_settings
from app.infrastructure.ffmpeg import ensure_ffmpeg_available, probe_duration
from app.services.rendering import rough_cut_service


def compose_local_video(
    media_dir_value: str,
    output_dir_value: str,
    output_filename_value: str,
    target_duration: float,
) -> dict:
    if target_duration <= 0:
        raise ValueError("视频时长必须大于 0 秒")

    media_dir = _require_directory(media_dir_value, "素材目录")
    output_dir = _require_directory(output_dir_value, "输出目录")
    output_filename = _normalize_output_filename(output_filename_value)
    output_path = (output_dir / output_filename).resolve()
    if output_path.parent != output_dir:
        raise ValueError("输出文件名不能包含目录")
    if output_path.exists():
        raise ValueError("输出文件已存在，请更换文件名后重试")

    ensure_ffmpeg_available()
    source_paths = rough_cut_service.scan_video_files(media_dir)
    groups = _group_by_filename(source_paths)
    settings = get_settings()
    effects = [item for item in settings.storyboard_transition_effects if item.enabled]
    transition_duration = settings.storyboard_transition_duration_seconds
    selected = rough_cut_service.select_videos_for_duration(
        groups,
        target_duration,
        transition_duration if effects else 0.0,
    )
    transition_plan = rough_cut_service.build_full_transition_plan(
        selected,
        effects,
        transition_duration,
    )

    with tempfile.TemporaryDirectory(prefix=".tubeaiflow-merge-", dir=output_dir) as temp_value:
        temp_dir = Path(temp_value)
        normalized_dir = temp_dir / "clips"
        normalized_dir.mkdir()
        normalized_paths = rough_cut_service.normalize_selected_clips(selected, normalized_dir)
        normalized_durations = [probe_duration(path) for path in normalized_paths]
        concat_path = temp_dir / "concat.txt"
        concat_path.write_text(
            "\n".join(f"file '{path.as_posix()}'" for path in normalized_paths),
            encoding="utf-8",
        )
        rough_cut_service.compose_normalized_clips(
            normalized_paths,
            normalized_durations,
            concat_path,
            temp_dir / "transition_filter.txt",
            transition_plan,
            output_path,
            output_duration=target_duration,
        )

    actual_duration = probe_duration(output_path)
    manifest_path = output_path.with_suffix(".manifest.json")
    manifest = {
        "output_path": str(output_path),
        "requested_duration": target_duration,
        "actual_duration": actual_duration,
        "scanned_file_count": len(source_paths),
        "unique_filename_count": len(groups),
        "selected_file_count": len(selected),
        "transition_count": len(transition_plan),
        "selected_files": [str(item.source_path) for item in selected],
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {**manifest, "manifest_path": str(manifest_path)}


def validate_local_video_input(
    media_dir_value: str,
    output_dir_value: str,
    output_filename_value: str,
    target_duration: float,
) -> tuple[Path, Path, str]:
    """Validate a queued request before it is accepted by the API."""
    if target_duration <= 0:
        raise ValueError("视频时长必须大于 0 秒")
    media_dir = _require_directory(media_dir_value, "素材目录")
    output_dir = _require_directory(output_dir_value, "输出目录")
    output_filename = _normalize_output_filename(output_filename_value)
    output_path = (output_dir / output_filename).resolve()
    if output_path.parent != output_dir:
        raise ValueError("输出文件名不能包含目录")
    if output_path.exists():
        raise ValueError("输出文件已存在，请更换文件名后重试")
    return media_dir, output_dir, output_filename


def _group_by_filename(paths: list[Path]) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = {}
    for path in paths:
        groups.setdefault(path.name.casefold(), []).append(path)
    return groups


def _require_directory(value: str, label: str) -> Path:
    path = Path(value.strip()).expanduser().resolve()
    if not value.strip() or not path.is_dir():
        raise ValueError(f"{label}不存在")
    return path


def _normalize_output_filename(value: str) -> str:
    filename = value.strip()
    if not filename:
        raise ValueError("请输入输出文件名")
    if Path(filename).name != filename or "/" in filename or "\\" in filename:
        raise ValueError("输出文件名不能包含目录")
    suffix = Path(filename).suffix.lower()
    if not suffix:
        filename += ".mp4"
    elif suffix != ".mp4":
        raise ValueError("输出文件必须使用 .mp4 格式")
    return filename
