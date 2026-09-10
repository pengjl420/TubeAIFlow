from __future__ import annotations

import ctypes
import os
import platform
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from app.config import get_settings


class _MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_ulong),
        ("memory_load", ctypes.c_ulong),
        ("total_physical", ctypes.c_ulonglong),
        ("available_physical", ctypes.c_ulonglong),
        ("total_page_file", ctypes.c_ulonglong),
        ("available_page_file", ctypes.c_ulonglong),
        ("total_virtual", ctypes.c_ulonglong),
        ("available_virtual", ctypes.c_ulonglong),
        ("available_extended_virtual", ctypes.c_ulonglong),
    ]


def hardware_status() -> dict:
    settings = get_settings()
    memory = _memory_status()
    disk_path = _existing_parent(settings.workspace_dir)
    disk = shutil.disk_usage(disk_path)
    gpus, cuda_version = _nvidia_status()
    encoders = _hardware_encoders(settings.ffmpeg_path)
    ffmpeg_available = bool(_resolve_executable(settings.ffmpeg_path))
    total_ram_gb = round(memory["total_bytes"] / 1024**3, 1) if memory else None
    free_disk_gb = round(disk.free / 1024**3, 1)
    if not ffmpeg_available or free_disk_gb < 5:
        rating = "limited"
    elif (total_ram_gb or 0) >= 16 and free_disk_gb >= 20:
        rating = "recommended" if gpus else "compatible"
    else:
        rating = "compatible"
    return {
        "rating": rating,
        "os": {
            "name": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
        },
        "cpu": {
            "name": platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "Unknown"),
            "logical_cores": os.cpu_count(),
        },
        "memory": {**(memory or {}), "total_gb": total_ram_gb},
        "disk": {
            "path": str(disk_path),
            "total_gb": round(disk.total / 1024**3, 1),
            "free_gb": free_disk_gb,
        },
        "gpus": gpus,
        "cuda_version": cuda_version,
        "ffmpeg_available": ffmpeg_available,
        "hardware_encoders": encoders,
        "recommended_encoder": next(
            (value for value in ("h264_nvenc", "h264_qsv", "h264_amf") if value in encoders),
            "libx264",
        ),
    }


def _memory_status() -> dict | None:
    if os.name != "nt":
        return None
    value = _MemoryStatus()
    value.length = ctypes.sizeof(_MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
        return None
    return {
        "total_bytes": value.total_physical,
        "available_bytes": value.available_physical,
        "load_percent": value.memory_load,
    }


def _nvidia_status() -> tuple[list[dict], str | None]:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return [], None
    try:
        result = subprocess.run(
            [
                executable,
                "--query-gpu=name,memory.total,memory.free,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            check=True,
        )
        version = subprocess.run(
            [executable],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return [], None
    gpus = []
    for index, line in enumerate(result.stdout.splitlines()):
        parts = [part.strip() for part in line.split(",")]
        if len(parts) >= 4:
            gpus.append(
                {
                    "index": index,
                    "name": parts[0],
                    "vram_total_mb": _integer(parts[1]),
                    "vram_free_mb": _integer(parts[2]),
                    "driver_version": parts[3],
                }
            )
    cuda_match = re.search(r"CUDA Version:\s*([\d.]+)", version)
    return gpus, cuda_match.group(1) if cuda_match else None


@lru_cache(maxsize=8)
def _hardware_encoders(configured: str) -> list[str]:
    executable = _resolve_executable(configured)
    if not executable:
        return []
    try:
        output = subprocess.run(
            [executable, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    names = (
        "h264_nvenc",
        "hevc_nvenc",
        "h264_qsv",
        "hevc_qsv",
        "h264_amf",
        "hevc_amf",
    )
    compiled = [name for name in names if name in output]
    return [name for name in compiled if _encoder_works(executable, name)]


def _encoder_works(executable: str, encoder: str) -> bool:
    """Verify that the encoder can open the current driver/device, not just that it is compiled."""
    try:
        result = subprocess.run(
            [
                executable,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=size=64x64:rate=1",
                "-frames:v",
                "1",
                "-an",
                "-c:v",
                encoder,
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _resolve_executable(value: str) -> str | None:
    path = Path(value)
    if path.is_file():
        return str(path.resolve())
    return shutil.which(path.name or value)


def _existing_parent(path: Path) -> Path:
    current = path.expanduser().resolve()
    while not current.exists() and current.parent != current:
        current = current.parent
    return current


def _integer(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None
