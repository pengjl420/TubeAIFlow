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
    command = [_resolve_tool(settings.ffmpeg_path, "ffmpeg.exe"), *args]
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
    stdout, stderr = process.communicate()
    task_control.check_cancelled(project_id)
    if process.returncode != 0:
        logger.error("FFmpeg failed: %s", stderr)
        raise RuntimeError(stderr.strip() or "FFmpeg command failed")


def probe_duration(audio_path: Path) -> float:
    settings = get_settings()
    command = [
        _resolve_tool(settings.ffprobe_path, "ffprobe.exe"),
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


def _resolve_tool(configured: str, executable_name: str) -> str:
    configured_path = Path(configured)
    if configured_path.is_absolute():
        return str(configured_path)

    found = shutil.which(configured)
    if found:
        return found

    settings = get_settings()
    if settings.index_tts_root:
        bundled = settings.index_tts_root / "python310" / "ffmpeg" / "bin" / executable_name
        if bundled.is_file():
            return str(bundled)

    return configured
