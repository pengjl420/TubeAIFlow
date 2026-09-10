from __future__ import annotations

import hashlib
import json
import logging
import queue
import re
import threading
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

from app.config import get_settings
from app.infrastructure.atomic_files import write_json_atomic
from app.shared.time import utc_now_iso


logger = logging.getLogger(__name__)
CHUNK_SIZE = 4 * 1024 * 1024
_lock = threading.RLock()
_jobs: dict[str, dict] = {}
_pending: queue.Queue[str] = queue.Queue()
_worker: threading.Thread | None = None


@dataclass(frozen=True, slots=True)
class LLMModelSpec:
    id: str
    display_name: str
    description: str
    repo_id: str
    filename: str
    size_bytes: int
    min_ram_gb: int
    recommended_vram_gb: int
    quality: str
    recommended: bool = False
    license: str = "Apache-2.0"

    @property
    def url(self) -> str:
        return f"https://huggingface.co/{self.repo_id}/resolve/main/{self.filename}?download=true"


MODEL_CATALOG = (
    LLMModelSpec(
        id="qwen3-4b-q4_k_m",
        display_name="Qwen3 4B Q4_K_M",
        description="轻量快速，适合低显存设备和草稿分镜。",
        repo_id="Qwen/Qwen3-4B-GGUF",
        filename="Qwen3-4B-Q4_K_M.gguf",
        size_bytes=2_500_000_000,
        min_ram_gb=8,
        recommended_vram_gb=6,
        quality="fast",
    ),
    LLMModelSpec(
        id="qwen3-8b-q4_k_m",
        display_name="Qwen3 8B Q4_K_M",
        description="质量、速度和显存占用均衡，适合作为默认语义模型。",
        repo_id="Qwen/Qwen3-8B-GGUF",
        filename="Qwen3-8B-Q4_K_M.gguf",
        size_bytes=5_030_000_000,
        min_ram_gb=16,
        recommended_vram_gb=10,
        quality="balanced",
        recommended=True,
    ),
    LLMModelSpec(
        id="qwen3-14b-q4_k_m",
        display_name="Qwen3 14B Q4_K_M",
        description="本地高质量模式，复杂叙事更稳，但生成更慢且占用更多显存。",
        repo_id="Qwen/Qwen3-14B-GGUF",
        filename="Qwen3-14B-Q4_K_M.gguf",
        size_bytes=9_000_000_000,
        min_ram_gb=24,
        recommended_vram_gb=16,
        quality="quality",
    ),
)
_catalog = {item.id: item for item in MODEL_CATALOG}


def list_models() -> list[dict]:
    with _lock:
        jobs = list(_jobs.values())
    latest_by_model = {item["model_id"]: item for item in jobs}
    return [_model_status(spec, latest_by_model.get(spec.id)) for spec in MODEL_CATALOG]


def get_model(model_id: str) -> dict:
    spec = _require_spec(model_id)
    with _lock:
        latest = next(
            (item for item in reversed(list(_jobs.values())) if item.get("model_id") == model_id),
            None,
        )
    return _model_status(spec, latest)


def enqueue_download(model_id: str) -> dict:
    spec = _require_spec(model_id)
    installed = _installed_path(spec)
    if installed:
        return {
            "id": f"installed:{model_id}",
            "model_id": model_id,
            "status": "completed",
            "progress": 100.0,
            "path": str(installed),
            "message": "模型已经安装",
        }
    with _lock:
        active = _active_job_for(model_id)
        if active:
            return dict(active)
        job_id = uuid.uuid4().hex
        job = {
            "id": job_id,
            "model_id": model_id,
            "status": "queued",
            "progress": 0.0,
            "downloaded_bytes": 0,
            "total_bytes": spec.size_bytes,
            "path": None,
            "message": "等待后台下载",
            "error": None,
            "created_at": utc_now_iso(),
            "updated_at": utc_now_iso(),
        }
        _jobs[job_id] = job
        _persist_jobs()
        _pending.put(job_id)
        _ensure_worker()
        return dict(job)


def get_job(job_id: str) -> dict:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise ValueError("模型下载任务不存在")
        return dict(job)


def recover_and_start_worker() -> None:
    global _jobs
    path = _state_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = []
    with _lock:
        _jobs = {
            item["id"]: item
            for item in payload
            if isinstance(item, dict) and item.get("id") and item.get("model_id") in _catalog
        }
        for job in _jobs.values():
            if job.get("status") in {"queued", "running", "interrupted"}:
                job["status"] = "queued"
                job["message"] = "应用重启后继续下载"
                _pending.put(job["id"])
        _persist_jobs()
    _ensure_worker()


def reset_for_tests() -> None:
    global _jobs, _worker, _pending
    with _lock:
        _jobs = {}
        _worker = None
        _pending = queue.Queue()


def _ensure_worker() -> None:
    global _worker
    with _lock:
        if _worker and _worker.is_alive():
            return
        _worker = threading.Thread(target=_worker_loop, name="llm-model-download", daemon=True)
        _worker.start()


def _worker_loop() -> None:
    while True:
        try:
            job_id = _pending.get(timeout=1)
        except queue.Empty:
            return
        try:
            _run_job(job_id)
        except Exception as exc:
            logger.exception("Local LLM model download failed")
            _update_job(job_id, status="failed", message="下载失败", error=str(exc))
        finally:
            _pending.task_done()


def _run_job(job_id: str) -> None:
    job = get_job(job_id)
    spec = _require_spec(job["model_id"])
    target_dir = get_settings().local_llm_models_dir / spec.id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / spec.filename
    partial = target.with_suffix(target.suffix + ".part")
    downloaded = partial.stat().st_size if partial.is_file() else 0
    headers = {"Range": f"bytes={downloaded}-"} if downloaded else {}
    _update_job(
        job_id,
        status="running",
        downloaded_bytes=downloaded,
        message="正在从官方模型仓库下载",
        error=None,
    )
    timeout = httpx.Timeout(600.0, connect=30.0)
    expected_sha256 = None
    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        expected_sha256 = _remote_sha256(client, spec)
        with client.stream("GET", spec.url, headers=headers) as response:
            response.raise_for_status()
            append = downloaded > 0 and response.status_code == 206
            if not append:
                downloaded = 0
            content_length = int(response.headers.get("content-length", "0") or 0)
            total = downloaded + content_length if content_length else spec.size_bytes
            if total > int(spec.size_bytes * 1.25):
                raise RuntimeError("下载文件大小超过模型清单允许范围")
            with partial.open("ab" if append else "wb") as output:
                last_reported = downloaded
                for chunk in response.iter_bytes(CHUNK_SIZE):
                    if not chunk:
                        continue
                    output.write(chunk)
                    downloaded += len(chunk)
                    if downloaded - last_reported < 64 * 1024 * 1024 and downloaded < total:
                        continue
                    last_reported = downloaded
                    progress = min(99.0, downloaded / max(1, total) * 100)
                    _update_job(
                        job_id,
                        progress=round(progress, 2),
                        downloaded_bytes=downloaded,
                        total_bytes=total,
                        message=f"已下载 {downloaded / 1024**3:.2f} GB",
                    )
    if downloaded < int(spec.size_bytes * 0.85):
        raise RuntimeError("模型文件不完整")
    with partial.open("rb") as stream:
        if stream.read(4) != b"GGUF":
            raise RuntimeError("下载内容不是有效的 GGUF 模型")
    digest = _sha256(partial)
    if expected_sha256 and digest != expected_sha256:
        raise RuntimeError("模型 SHA-256 校验失败，文件可能不完整")
    partial.replace(target)
    write_json_atomic(
        target_dir / "source.json",
        {
            "model_id": spec.id,
            "repo_id": spec.repo_id,
            "filename": spec.filename,
            "source": spec.url,
            "license": spec.license,
            "size_bytes": target.stat().st_size,
            "sha256": digest,
            "verified_against_remote": bool(expected_sha256),
            "installed_at": utc_now_iso(),
        },
    )
    _update_job(
        job_id,
        status="completed",
        progress=100.0,
        downloaded_bytes=target.stat().st_size,
        total_bytes=target.stat().st_size,
        path=str(target),
        message="下载完成并通过 GGUF 校验",
    )


def _model_status(spec: LLMModelSpec, job: dict | None) -> dict:
    path = _installed_path(spec)
    return {
        **asdict(spec),
        "installed": path is not None,
        "path": str(path) if path else None,
        "download": dict(job) if job else None,
    }


def _installed_path(spec: LLMModelSpec) -> Path | None:
    path = get_settings().local_llm_models_dir / spec.id / spec.filename
    if not path.is_file() or path.stat().st_size < int(spec.size_bytes * 0.85):
        return None
    try:
        with path.open("rb") as stream:
            return path if stream.read(4) == b"GGUF" else None
    except OSError:
        return None


def _active_job_for(model_id: str) -> dict | None:
    with _lock:
        return next(
            (
                dict(item)
                for item in _jobs.values()
                if item.get("model_id") == model_id and item.get("status") in {"queued", "running"}
            ),
            None,
        )


def _require_spec(model_id: str) -> LLMModelSpec:
    try:
        return _catalog[model_id]
    except KeyError as exc:
        raise ValueError("不支持的本地语义模型") from exc


def _update_job(job_id: str, **values) -> None:
    with _lock:
        if job_id not in _jobs:
            return
        _jobs[job_id].update(values, updated_at=utc_now_iso())
        _persist_jobs()


def _persist_jobs() -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, list(_jobs.values()))


def _state_path() -> Path:
    return get_settings().workspace_dir / "model_downloads" / "llm_downloads.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _remote_sha256(client: httpx.Client, spec: LLMModelSpec) -> str | None:
    """Read the immutable content digest advertised by the official repository."""
    try:
        response = client.get(f"https://huggingface.co/api/models/{spec.repo_id}/revision/main")
        response.raise_for_status()
        siblings = response.json().get("siblings", [])
        item = next(
            (entry for entry in siblings if entry.get("rfilename") == spec.filename),
            None,
        )
        if not isinstance(item, dict):
            return None
        candidates = [
            (item.get("lfs") or {}).get("oid") if isinstance(item.get("lfs"), dict) else None,
            item.get("xetHash"),
        ]
        for candidate in candidates:
            digest = str(candidate or "").removeprefix("sha256:").lower()
            if re.fullmatch(r"[0-9a-f]{64}", digest):
                return digest
    except (httpx.HTTPError, ValueError, TypeError, StopIteration):
        return None
    return None
