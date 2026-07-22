import json
import logging
import shutil
import subprocess
from pathlib import Path

from app.config import get_settings
from app.infrastructure import process_runner as task_control


logger = logging.getLogger(__name__)


def run_ffmpeg(args: list[str], project_id: str | None = None) -> None:
    settings = get_settings()
    command = [_resolve_tool(settings.ffmpeg_path), *args]
    try:
        if not project_id:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if result.returncode != 0:
                logger.error("FFmpeg failed: %s", result.stderr)
                raise RuntimeError(result.stderr.strip() or "FFmpeg command failed")
            return
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"FFmpeg executable was not found: {command[0]}") from exc
    task_control.register_process(project_id, process)
    try:
        stdout, stderr = process.communicate()
    finally:
        task_control.unregister_process(project_id, process)
    task_control.check_cancelled(project_id)
    if process.returncode != 0:
        logger.error("FFmpeg failed: %s", stderr)
        raise RuntimeError(stderr.strip() or "FFmpeg command failed")


def probe_duration(audio_path: Path) -> float:
    settings = get_settings()
    command = [
        _resolve_tool(settings.ffprobe_path),
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(audio_path),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"ffprobe executable was not found: {command[0]}") from exc
    if result.returncode != 0:
        logger.error("ffprobe failed for %s: %s", audio_path, result.stderr)
        raise RuntimeError(result.stderr.strip() or "ffprobe command failed")
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def probe_media(media_path: Path) -> dict:
    """Read stable container and primary-video metadata with ffprobe."""
    settings = get_settings()
    command = [
        _resolve_tool(settings.ffprobe_path),
        "-v",
        "error",
        "-show_entries",
        "format=duration,format_name:stream=index,codec_type,codec_name,width,height,pix_fmt,r_frame_rate,avg_frame_rate,time_base,duration_ts,nb_frames",
        "-of",
        "json",
        str(media_path),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"ffprobe executable was not found: {command[0]}") from exc
    if result.returncode != 0:
        logger.error("ffprobe failed for %s: %s", media_path, result.stderr)
        raise RuntimeError(result.stderr.strip() or "ffprobe command failed")

    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
    audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
    video_stream = next(
        iter(video_streams),
        {},
    )
    raw_duration = data.get("format", {}).get("duration")
    frame_rate = video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate")
    return {
        "duration_ms": round(float(raw_duration) * 1000) if raw_duration else None,
        "width": video_stream.get("width"),
        "height": video_stream.get("height"),
        "codec_name": video_stream.get("codec_name"),
        "pixel_format": video_stream.get("pix_fmt"),
        "frame_rate": frame_rate,
        "frame_rate_value": _parse_frame_rate(frame_rate),
        "time_base": video_stream.get("time_base"),
        "duration_ts": _parse_optional_int(video_stream.get("duration_ts")),
        "frame_count": _parse_optional_int(video_stream.get("nb_frames")),
        "video_stream_count": len(video_streams),
        "audio_stream_count": len(audio_streams),
        "format_name": data.get("format", {}).get("format_name"),
    }


def _parse_frame_rate(value: str | None) -> float | None:
    if not value:
        return None
    numerator, separator, denominator = value.partition("/")
    try:
        if not separator:
            return float(numerator)
        divisor = float(denominator)
        return float(numerator) / divisor if divisor else None
    except ValueError:
        return None


def _parse_optional_int(value: str | int | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _resolve_tool(configured: str) -> str:
    configured_path = Path(configured)
    if configured_path.is_absolute():
        return str(configured_path)

    found = shutil.which(configured)
    if found:
        return found

    return configured
