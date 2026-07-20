from __future__ import annotations

import time

import httpx

from app.config import Settings
from app.infrastructure import process_runner as task_control
from app.integrations.framepack import process_manager
from app.integrations.framepack.schemas import (
    FramePackHealth,
    FramePackJobRead,
    FramePackJobRequest,
)


class FramePackError(RuntimeError):
    pass


class FramePackUnavailableError(FramePackError):
    pass


class FramePackOOMError(FramePackError):
    pass


class FramePackTimeoutError(FramePackError):
    pass


class FramePackClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = f"http://{settings.framepack_worker_host}:{settings.framepack_worker_port}"

    def health(self, start_if_needed: bool = False) -> FramePackHealth:
        try:
            health = self._get_health()
            if start_if_needed and health.status in {"starting", "loading_model"}:
                return self._wait_until_ready()
            return health
        except (httpx.HTTPError, ValueError) as exc:
            if start_if_needed and self.settings.framepack_auto_start_worker:
                process_manager.ensure_worker(self.settings)
                return self._wait_until_ready()
            raise FramePackUnavailableError(f"FramePack Worker 不可用：{exc}") from exc

    def render(self, request: FramePackJobRequest, project_id: str) -> FramePackJobRead:
        health = self.health(start_if_needed=True)
        if health.status not in {"ready", "busy"}:
            raise FramePackUnavailableError(health.error or f"FramePack Worker 状态为 {health.status}")
        try:
            response = httpx.post(
                f"{self.base_url}/jobs",
                json=request.model_dump(),
                timeout=30,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise FramePackUnavailableError(f"无法提交 FramePack 任务：{exc}") from exc

        task_control.register_cancel_callback(project_id, lambda: self.cancel(request.job_id))
        started = time.monotonic()
        try:
            while True:
                task_control.check_cancelled(project_id)
                if time.monotonic() - started > self.settings.framepack_job_timeout_seconds:
                    self.cancel(request.job_id)
                    raise FramePackTimeoutError("FramePack 镜头生成超时")
                job = self.get_job(request.job_id)
                if job.status == "completed":
                    return job
                if job.status == "cancelled":
                    raise FramePackError("FramePack 任务已取消")
                if job.status == "failed":
                    message = job.error or "FramePack 任务失败"
                    if "out of memory" in message.casefold() or "cuda oom" in message.casefold():
                        raise FramePackOOMError(message)
                    raise FramePackError(message)
                time.sleep(1)
        finally:
            task_control.register_cancel_callback(project_id, None)

    def get_job(self, job_id: str) -> FramePackJobRead:
        try:
            response = httpx.get(f"{self.base_url}/jobs/{job_id}", timeout=15)
            response.raise_for_status()
            return FramePackJobRead.model_validate(response.json())
        except (httpx.HTTPError, ValueError) as exc:
            raise FramePackUnavailableError(f"无法读取 FramePack 任务：{exc}") from exc

    def cancel(self, job_id: str) -> None:
        try:
            httpx.post(f"{self.base_url}/jobs/{job_id}/cancel", timeout=10)
        except httpx.HTTPError:
            pass

    def _get_health(self) -> FramePackHealth:
        response = httpx.get(f"{self.base_url}/health", timeout=10)
        response.raise_for_status()
        return FramePackHealth.model_validate(response.json())

    def _wait_until_ready(self) -> FramePackHealth:
        started = time.monotonic()
        last_error = "Worker 尚未响应"
        while time.monotonic() - started <= self.settings.framepack_startup_timeout_seconds:
            try:
                health = self._get_health()
                if health.status in {"ready", "busy"}:
                    return health
                if health.status in {"unavailable", "error"}:
                    raise FramePackUnavailableError(health.error or health.status)
                last_error = health.error or health.status
            except httpx.HTTPError as exc:
                last_error = str(exc)
            time.sleep(1)
        raise FramePackUnavailableError(f"FramePack Worker 启动超时：{last_error}")
