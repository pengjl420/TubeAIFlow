from __future__ import annotations

import os
import queue
import threading
import time
import traceback
from dataclasses import dataclass, field

import uvicorn
from fastapi import FastAPI, HTTPException

try:
    from .engine import FramePackCancelled, FramePackEngine
except ImportError:
    from engine import FramePackCancelled, FramePackEngine

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.integrations.framepack.schemas import (  # noqa: E402
    FramePackHealth,
    FramePackJobRead,
    FramePackJobRequest,
)


@dataclass
class JobState:
    request: FramePackJobRequest
    status: str = "queued"
    progress: int = 0
    generated_frames: int = 0
    output_path: str | None = None
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def read(self) -> FramePackJobRead:
        end = self.finished_at or time.monotonic()
        elapsed = end - self.started_at if self.started_at else 0
        return FramePackJobRead(
            job_id=self.request.job_id,
            status=self.status,
            progress=self.progress,
            generated_frames=self.generated_frames,
            elapsed_seconds=round(max(0, elapsed), 2),
            output_path=self.output_path,
            error=self.error,
        )


app = FastAPI(title="TubeAIFlow FramePack Worker")
engine = FramePackEngine()
jobs: dict[str, JobState] = {}
job_queue: queue.Queue[str] = queue.Queue()
state_lock = threading.Lock()
worker_status = "starting"
worker_error: str | None = None
current_job_id: str | None = None


@app.on_event("startup")
def start_worker() -> None:
    threading.Thread(target=_worker_loop, name="framepack-worker", daemon=True).start()


@app.get("/health", response_model=FramePackHealth)
def health() -> FramePackHealth:
    gpu, free_vram = engine.gpu_info()
    return FramePackHealth(
        status="busy" if current_job_id else worker_status,
        model_loaded=engine.pipeline is not None,
        gpu=gpu,
        free_vram_gb=free_vram,
        current_job_id=current_job_id,
        error=worker_error,
    )


@app.post("/jobs", response_model=FramePackJobRead)
def submit_job(request: FramePackJobRequest) -> FramePackJobRead:
    with state_lock:
        if request.job_id in jobs:
            existing = jobs[request.job_id]
            if existing.request != request:
                raise HTTPException(status_code=409, detail="job_id 已存在且参数不同")
            return existing.read()
        job = JobState(request=request)
        jobs[request.job_id] = job
        job_queue.put(request.job_id)
        return job.read()


@app.get("/jobs/{job_id}", response_model=FramePackJobRead)
def get_job(job_id: str) -> FramePackJobRead:
    with state_lock:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="FramePack 任务不存在")
        return job.read()


@app.post("/jobs/{job_id}/cancel", response_model=FramePackJobRead)
def cancel_job(job_id: str) -> FramePackJobRead:
    with state_lock:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="FramePack 任务不存在")
        job.cancel_event.set()
        if job.status == "queued":
            job.status = "cancelled"
            job.finished_at = time.monotonic()
        return job.read()


def _worker_loop() -> None:
    global worker_status, worker_error, current_job_id
    worker_status = "loading_model"
    try:
        engine.load()
    except Exception as exc:
        worker_status = "unavailable"
        worker_error = f"{type(exc).__name__}: {exc}"
    else:
        worker_status = "ready"
    while True:
        job_id = job_queue.get()
        with state_lock:
            job = jobs[job_id]
            if job.status == "cancelled":
                continue
            if worker_status != "ready":
                job.status = "failed"
                job.error = worker_error or "FramePack 模型不可用"
                job.finished_at = time.monotonic()
                continue
            job.status = "sampling"
            job.started_at = time.monotonic()
            current_job_id = job_id
        try:
            output = engine.generate(
                job.request,
                job.cancel_event,
                lambda progress, frames: _update_progress(job, progress, frames),
            )
            with state_lock:
                job.status = "completed"
                job.progress = 100
                job.output_path = str(output)
        except FramePackCancelled as exc:
            with state_lock:
                job.status = "cancelled"
                job.error = str(exc)
        except Exception as exc:
            traceback.print_exc()
            with state_lock:
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {exc}"
        finally:
            with state_lock:
                job.finished_at = time.monotonic()
                current_job_id = None


def _update_progress(job: JobState, progress: int, frames: int) -> None:
    with state_lock:
        job.progress = progress
        job.generated_frames = frames
        if progress >= 97 and job.status == "sampling":
            job.status = "encoding"


if __name__ == "__main__":
    host = os.environ.get("FRAMEPACK_HOST", "127.0.0.1")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("FramePack Worker 只允许监听本机地址")
    uvicorn.run(app, host=host, port=int(os.environ.get("FRAMEPACK_PORT", "7861")))
