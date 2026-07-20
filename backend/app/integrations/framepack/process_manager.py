from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path

from app.config import Settings


_LOCK = threading.Lock()
_PROCESS: subprocess.Popen | None = None
_LOG_HANDLE = None


def ensure_worker(settings: Settings) -> subprocess.Popen:
    global _PROCESS, _LOG_HANDLE
    with _LOCK:
        if _PROCESS is not None and _PROCESS.poll() is None:
            return _PROCESS
        if settings.framepack_python is None or not settings.framepack_python.is_file():
            raise RuntimeError("尚未配置 FramePack 独立 Python")
        server = Path(__file__).resolve().parents[3] / "framepack_worker" / "worker_server.py"
        if not server.is_file():
            raise RuntimeError(f"FramePack Worker 入口不存在：{server}")
        environment = os.environ.copy()
        environment.update(
            {
                "FRAMEPACK_HOST": settings.framepack_worker_host,
                "FRAMEPACK_PORT": str(settings.framepack_worker_port),
                "FRAMEPACK_MODEL_ID": settings.framepack_model_id,
                "FRAMEPACK_BASE_MODEL_ID": settings.framepack_base_model_id,
                "FRAMEPACK_SAMPLING_TYPE": settings.framepack_sampling_type,
                "FRAMEPACK_ALLOW_MODEL_DOWNLOAD": "1" if settings.framepack_allow_model_download else "0",
                "FRAMEPACK_CPU_OFFLOAD": "1" if settings.framepack_cpu_offload else "0",
                "FRAMEPACK_ALLOWED_ROOT": str(settings.workspace_dir),
            }
        )
        if settings.framepack_cache_dir is not None:
            environment["HF_HOME"] = str(settings.framepack_cache_dir)
        if _LOG_HANDLE is not None:
            _LOG_HANDLE.close()
        log_path = settings.workspace_dir / "logs" / "framepack_worker.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        _LOG_HANDLE = log_path.open("a", encoding="utf-8")
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        _PROCESS = subprocess.Popen(
            [str(settings.framepack_python), "-u", str(server)],
            cwd=str(server.parent),
            env=environment,
            stdout=_LOG_HANDLE,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        return _PROCESS


def worker_process_status() -> dict:
    with _LOCK:
        return {
            "managed": _PROCESS is not None,
            "running": bool(_PROCESS is not None and _PROCESS.poll() is None),
            "pid": _PROCESS.pid if _PROCESS is not None and _PROCESS.poll() is None else None,
        }
