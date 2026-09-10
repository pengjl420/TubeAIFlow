from __future__ import annotations

from collections import namedtuple
from types import SimpleNamespace
from unittest.mock import patch

from app.services.settings import hardware_service


DiskUsage = namedtuple("DiskUsage", "total used free")


def _gb(value: int) -> int:
    return value * 1024**3


def test_hardware_status_recommends_detected_gpu_encoder(tmp_path) -> None:
    settings = SimpleNamespace(workspace_dir=tmp_path, ffmpeg_path="ffmpeg")
    gpu = {
        "index": 0,
        "name": "NVIDIA RTX Test",
        "vram_total_mb": 12288,
        "vram_free_mb": 10000,
        "driver_version": "999.1",
    }
    with (
        patch.object(hardware_service, "get_settings", return_value=settings),
        patch.object(
            hardware_service,
            "_memory_status",
            return_value={"total_bytes": _gb(32), "load_percent": 25},
        ),
        patch.object(
            hardware_service.shutil,
            "disk_usage",
            return_value=DiskUsage(_gb(200), _gb(100), _gb(100)),
        ),
        patch.object(hardware_service, "_nvidia_status", return_value=([gpu], "13.0")),
        patch.object(hardware_service, "_hardware_encoders", return_value=["h264_nvenc"]),
        patch.object(hardware_service, "_resolve_executable", return_value="ffmpeg.exe"),
    ):
        status = hardware_service.hardware_status()

    assert status["rating"] == "recommended"
    assert status["recommended_encoder"] == "h264_nvenc"
    assert status["cuda_version"] == "13.0"
    assert status["memory"]["total_gb"] == 32.0


def test_hardware_status_marks_missing_ffmpeg_as_limited(tmp_path) -> None:
    settings = SimpleNamespace(workspace_dir=tmp_path, ffmpeg_path="missing")
    with (
        patch.object(hardware_service, "get_settings", return_value=settings),
        patch.object(
            hardware_service,
            "_memory_status",
            return_value={"total_bytes": _gb(16), "load_percent": 10},
        ),
        patch.object(
            hardware_service.shutil,
            "disk_usage",
            return_value=DiskUsage(_gb(200), _gb(100), _gb(100)),
        ),
        patch.object(hardware_service, "_nvidia_status", return_value=([], None)),
        patch.object(hardware_service, "_hardware_encoders", return_value=[]),
        patch.object(hardware_service, "_resolve_executable", return_value=None),
    ):
        status = hardware_service.hardware_status()

    assert status["rating"] == "limited"
    assert status["recommended_encoder"] == "libx264"
    assert status["ffmpeg_available"] is False


def test_compiled_encoder_is_rejected_when_device_cannot_open() -> None:
    hardware_service._hardware_encoders.cache_clear()
    listing = SimpleNamespace(stdout=" V..... h264_nvenc NVIDIA NVENC", returncode=0)
    failed_probe = SimpleNamespace(stdout="", returncode=1)
    with (
        patch.object(hardware_service, "_resolve_executable", return_value="ffmpeg.exe"),
        patch.object(hardware_service.subprocess, "run", side_effect=[listing, failed_probe]),
    ):
        assert hardware_service._hardware_encoders("ffmpeg") == []
    hardware_service._hardware_encoders.cache_clear()
