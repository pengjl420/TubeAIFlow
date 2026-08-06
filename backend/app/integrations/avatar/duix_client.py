from __future__ import annotations

import time
from pathlib import Path, PurePosixPath

import httpx

from app.config import get_settings


class DuixClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = settings.duix_base_url.rstrip("/")
        self.host_root = settings.duix_host_shared_dir.resolve()
        self.container_root = PurePosixPath(settings.duix_container_shared_dir)
        self.poll_interval = settings.duix_poll_interval_seconds
        self.task_timeout = settings.duix_task_timeout_seconds

    def health_check(self) -> dict:
        try:
            response = httpx.get(
                f"{self.base_url}/easy/query",
                params={"code": "tubeaiflow-health-check"},
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
            return {"available": True, "service_code": payload.get("code"), "message": payload.get("msg", "")}
        except (httpx.HTTPError, ValueError) as exc:
            return {"available": False, "error": str(exc)}

    def to_container_path(self, host_path: Path) -> str:
        resolved = host_path.resolve()
        try:
            relative = resolved.relative_to(self.host_root)
        except ValueError as exc:
            raise ValueError(f"Duix 输入必须位于共享目录：{self.host_root}") from exc
        if ".." in relative.parts:
            raise ValueError("Duix 共享路径不允许目录穿越")
        return str(self.container_root.joinpath(*relative.parts))

    def expected_result_path(self, code: str) -> Path:
        safe_code = str(code or "").strip()
        if not safe_code or "/" in safe_code or "\\" in safe_code or ".." in safe_code:
            raise ValueError("Duix 任务码无效")
        return (self.host_root / "temp" / f"{safe_code}-r.mp4").resolve()

    def to_host_path(self, container_path: str, *, expected_code: str | None = None) -> Path:
        value = PurePosixPath(str(container_path))
        try:
            relative = value.relative_to(self.container_root)
            resolved = self.host_root.joinpath(*relative.parts).resolve()
        except ValueError:
            # The local Duix wrapper exposes a completed result as
            # "/{task_code}-r.mp4", while the file is physically written to
            # /code/data/temp/{task_code}-r.mp4. Only accept the exact filename
            # for the task being polled; arbitrary root paths remain rejected.
            expected_name = f"{expected_code}-r.mp4" if expected_code else ""
            if value.parent != PurePosixPath("/") or value.name != expected_name:
                raise ValueError("Duix 返回了共享目录之外的文件路径")
            resolved = self.expected_result_path(expected_code)
        try:
            resolved.relative_to(self.host_root)
        except ValueError as exc:
            raise ValueError("Duix 返回路径包含目录穿越") from exc
        return resolved

    def submit(self, *, audio_path: Path, video_path: Path, code: str) -> None:
        payload = {
            "audio_url": self.to_container_path(audio_path),
            "video_url": self.to_container_path(video_path),
            "code": code,
            "chaofen": 0,
            "watermark_switch": 0,
            "pn": 1,
        }
        response = httpx.post(f"{self.base_url}/easy/submit", json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        if data.get("code") == 10001:
            raise RuntimeError("Duix 正忙，请稍后重试")
        if data.get("code") != 10000 or not data.get("success"):
            raise RuntimeError(data.get("msg") or "Duix 拒绝了生成任务")

    def wait_for_result(self, code: str, on_progress=None) -> dict:
        deadline = time.monotonic() + self.task_timeout
        while time.monotonic() < deadline:
            response = httpx.get(
                f"{self.base_url}/easy/query",
                params={"code": code},
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") != 10000:
                raise RuntimeError(payload.get("msg") or "Duix 查询任务失败")
            data = payload.get("data") or {}
            status = int(data.get("status") or 0)
            progress = float(data.get("progress") or 0)
            if on_progress:
                on_progress(progress)
            if status == 2:
                result = str(data.get("result") or "").strip()
                if not result:
                    raise RuntimeError("Duix 报告成功但未返回视频路径")
                data["host_result_path"] = str(
                    self.to_host_path(result, expected_code=code)
                )
                return data
            if status == 3:
                raise RuntimeError(str(data.get("msg") or "Duix 生成失败"))
            time.sleep(self.poll_interval)
        raise TimeoutError(f"Duix 任务超过 {self.task_timeout:.0f} 秒仍未完成")
