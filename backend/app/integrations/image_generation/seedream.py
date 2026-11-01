from __future__ import annotations

import base64
import binascii
import json
import time
from pathlib import Path

import httpx
from PIL import Image

from app.config import Settings, get_settings
from app.infrastructure import process_runner as task_control
from app.integrations.tts.runner_io import write_json
from app.providers import ImageBatchRequest


SEEDREAM_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
SEEDREAM_MODEL_ID = "doubao-seedream-5-0-260128"
SEEDREAM_SIZE = "2848x1600"
SEEDREAM_OUTPUT_FORMAT = "png"
SEEDREAM_RESPONSE_FORMAT = "b64_json"
SEEDREAM_WATERMARK = False
SEEDREAM_TIMEOUT_SECONDS = 300.0
SEEDREAM_RETRY_COUNT = 2


class SeedreamClient:
    """Synchronous Volcengine Ark image client used by persisted workflow jobs."""

    def __init__(self, settings: Settings | None = None, project_id: str | None = None) -> None:
        self.settings = settings or get_settings()
        self.project_id = project_id

    def generate(self, *, prompt: str, output_path: Path) -> float:
        if not self.settings.seedream_api_key.strip():
            raise ValueError("系统尚未配置火山方舟 Seedream API Key")
        endpoint = SEEDREAM_BASE_URL.rstrip("/")
        if not endpoint.endswith("/images/generations"):
            endpoint = f"{endpoint}/images/generations"
        payload = {
            "model": SEEDREAM_MODEL_ID,
            "prompt": prompt,
            "size": SEEDREAM_SIZE,
            "output_format": SEEDREAM_OUTPUT_FORMAT,
            "response_format": SEEDREAM_RESPONSE_FORMAT,
            "watermark": SEEDREAM_WATERMARK,
        }
        last_error: Exception | None = None
        for _attempt in range(SEEDREAM_RETRY_COUNT + 1):
            if self.project_id:
                task_control.check_cancelled(self.project_id)
            client = httpx.Client(timeout=SEEDREAM_TIMEOUT_SECONDS)
            if self.project_id:
                task_control.register_cancel_callback(self.project_id, client.close)
            started = time.monotonic()
            try:
                response = client.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {self.settings.seedream_api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                if self.project_id:
                    task_control.check_cancelled(self.project_id)
                response.raise_for_status()
                data = response.json()
                encoded = data["data"][0]["b64_json"]
                if not isinstance(encoded, str) or not encoded:
                    raise RuntimeError("Seedream 返回了空图片")
                image_bytes = base64.b64decode(encoded, validate=True)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = output_path.with_suffix(f"{output_path.suffix}.tmp")
                temporary.write_bytes(image_bytes)
                with Image.open(temporary) as image:
                    image.verify()
                temporary.replace(output_path)
                return time.monotonic() - started
            except task_control.TaskCancelledError:
                raise
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                if status_code not in {408, 409, 425, 429} and status_code < 500:
                    raise RuntimeError(
                        f"Seedream 请求失败：HTTP {status_code}，请检查模型与凭据配置"
                    ) from exc
                last_error = exc
            except (
                httpx.RequestError,
                OSError,
                KeyError,
                IndexError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
                binascii.Error,
                RuntimeError,
            ) as exc:
                last_error = exc
            finally:
                if self.project_id:
                    task_control.register_cancel_callback(self.project_id, None)
                client.close()
        raise RuntimeError(f"Seedream 请求失败：{last_error}") from last_error


def generate_batch(request: ImageBatchRequest) -> None:
    """Generate one durable local PNG for every persisted candidate request."""
    request.result_path.unlink(missing_ok=True)
    write_json(request.batch_path, list(request.jobs))
    results: list[dict] = []
    failed = 0
    client = SeedreamClient(project_id=request.project_id)
    for index, job in enumerate(request.jobs, start=1):
        try:
            seconds = client.generate(
                prompt=str(job["provider_prompt"]),
                output_path=Path(job["output_path"]),
            )
            result = {
                "variant_id": job["variant_id"],
                "output_path": job["output_path"],
                "status": "completed",
                "generation_seconds": seconds,
            }
        except task_control.TaskCancelledError:
            raise
        except Exception as exc:
            failed += 1
            result = {
                "variant_id": job["variant_id"],
                "output_path": job["output_path"],
                "status": "failed",
                "error": str(exc),
            }
        results.append(result)
        write_json(request.result_path, results)
        write_json(
            request.progress_path,
            {
                "status": "running" if index < len(request.jobs) else "completed",
                "completed": index - failed,
                "failed": failed,
                "total": len(request.jobs),
            },
        )
