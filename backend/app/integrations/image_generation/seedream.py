from __future__ import annotations

import base64
import binascii
import json
import time
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx
from PIL import Image

from app.config import Settings, get_settings
from app.infrastructure import process_runner as task_control
from app.integrations.tts.runner_io import write_json
from app.providers import ImageBatchRequest


SEEDREAM_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
SEEDREAM_PRO_MODEL_ID = "doubao-seedream-5-0-pro-260628"
SEEDREAM_FLASH_MODEL_ID = "doubao-seedream-5-0-flash-260915"
# Import-compatible default for callers that have not selected a model explicitly.
SEEDREAM_MODEL_ID = SEEDREAM_PRO_MODEL_ID
SEEDREAM_SIZE = "2848x1600"
SEEDREAM_OUTPUT_FORMAT = "png"
SEEDREAM_RESPONSE_FORMAT = "b64_json"
SEEDREAM_WATERMARK = False
SEEDREAM_TIMEOUT_SECONDS = 600.0
SEEDREAM_RETRY_COUNT = 2


class SeedreamAPIError(RuntimeError):
    """Actionable Ark API failure without exposing credentials or response headers."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class SeedreamResultUnknownError(RuntimeError):
    """The provider may have accepted a paid generation request.

    Retrying these failures automatically can create a second image and a
    second charge, so callers must persist the candidate as requiring review.
    """

    code = "SEEDREAM_RESULT_UNKNOWN"


def _retry_delay_seconds(response: httpx.Response, attempt: int) -> float:
    value = str(response.headers.get("retry-after") or "").strip()
    if value:
        try:
            return max(0.0, min(60.0, float(value)))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
                delay = retry_at.timestamp() - time.time()
                return max(0.0, min(60.0, delay))
            except (TypeError, ValueError, OverflowError):
                pass
    return min(8.0, float(2**attempt))


def _api_error(response: httpx.Response, *, model_id: str) -> SeedreamAPIError:
    status_code = response.status_code
    provider_code = ""
    provider_message = ""
    try:
        payload = response.json()
        error = payload.get("error", payload) if isinstance(payload, dict) else {}
        if isinstance(error, dict):
            provider_code = str(error.get("code") or "").strip()
            provider_message = str(error.get("message") or "").strip()
    except (ValueError, json.JSONDecodeError):
        pass

    if status_code == 401:
        code = "SEEDREAM_AUTH_FAILED"
        guidance = "火山方舟 API Key 无效、已过期或不属于当前区域"
    elif status_code in {403, 404}:
        code = "SEEDREAM_MODEL_UNAVAILABLE"
        guidance = f"模型 {model_id} 不存在、未开通或当前账号无权访问"
    elif status_code == 429:
        code = "SEEDREAM_RATE_LIMITED"
        guidance = "请求超过火山方舟配额或并发限制"
    elif status_code >= 500:
        code = "SEEDREAM_SERVICE_UNAVAILABLE"
        guidance = "火山方舟服务暂时不可用"
    else:
        code = "SEEDREAM_REQUEST_FAILED"
        guidance = "请求参数或模型配置不被火山方舟接受"

    detail_parts = [item for item in (provider_code, provider_message) if item]
    detail = f"；服务端：{' - '.join(detail_parts)[:500]}" if detail_parts else ""
    request_id = str(
        response.headers.get("x-request-id") or response.headers.get("x-tt-logid") or ""
    ).strip()
    request_suffix = f"；Request ID：{request_id[:128]}" if request_id else ""
    return SeedreamAPIError(
        f"Seedream 请求失败：HTTP {status_code}，{guidance}{detail}{request_suffix}",
        code=code,
    )


class SeedreamClient:
    """Synchronous Volcengine Ark image client used by persisted workflow jobs."""

    def __init__(
        self,
        settings: Settings | None = None,
        project_id: str | None = None,
        *,
        model_id: str = SEEDREAM_MODEL_ID,
    ) -> None:
        self.settings = settings or get_settings()
        self.project_id = project_id
        self.model_id = model_id

    def generate(self, *, prompt: str, output_path: Path) -> float:
        if not self.settings.seedream_api_key.strip():
            raise ValueError("系统尚未配置火山方舟 Seedream API Key")
        endpoint = SEEDREAM_BASE_URL.rstrip("/")
        if not endpoint.endswith("/images/generations"):
            endpoint = f"{endpoint}/images/generations"
        payload = {
            "model": self.model_id,
            "prompt": prompt,
            "size": SEEDREAM_SIZE,
            "output_format": SEEDREAM_OUTPUT_FORMAT,
            "response_format": SEEDREAM_RESPONSE_FORMAT,
            "watermark": SEEDREAM_WATERMARK,
        }
        last_error: Exception | None = None
        for attempt in range(SEEDREAM_RETRY_COUNT + 1):
            if self.project_id:
                task_control.check_cancelled(self.project_id)
            client = httpx.Client(
                timeout=httpx.Timeout(
                    SEEDREAM_TIMEOUT_SECONDS,
                    connect=10.0,
                    write=30.0,
                    pool=10.0,
                )
            )
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
                api_error = _api_error(exc.response, model_id=self.model_id)
                # These responses explicitly reject the current attempt before
                # a usable result is produced. Retrying them cannot duplicate a
                # successful image. Read timeouts and 5xx responses are handled
                # as ambiguous instead.
                if status_code in {409, 425, 429}:
                    last_error = api_error
                    if attempt < SEEDREAM_RETRY_COUNT:
                        time.sleep(_retry_delay_seconds(exc.response, attempt))
                    continue
                if status_code == 408 or status_code >= 500:
                    raise SeedreamResultUnknownError(
                        f"Seedream 请求结果未知（HTTP {status_code}）；为避免重复生成和重复计费，系统未自动重试"
                    ) from exc
                else:
                    raise api_error from exc
            except (httpx.ConnectTimeout, httpx.ConnectError, httpx.PoolTimeout) as exc:
                # No provider response was established, so retrying is safe.
                last_error = exc
                if attempt < SEEDREAM_RETRY_COUNT:
                    time.sleep(min(8.0, float(2**attempt)))
            except httpx.RequestError as exc:
                raise SeedreamResultUnknownError(
                    "Seedream 请求已发送但响应中断；为避免重复生成和重复计费，系统未自动重试"
                ) from exc
            except (
                OSError,
                KeyError,
                IndexError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
                binascii.Error,
                RuntimeError,
            ) as exc:
                # The provider has already returned at this point. Repeating the
                # paid request cannot repair a local decode or filesystem error.
                raise RuntimeError(f"Seedream 结果保存失败：{exc}") from exc
            finally:
                if self.project_id:
                    task_control.register_cancel_callback(self.project_id, None)
                client.close()
        if isinstance(last_error, SeedreamAPIError):
            raise last_error
        raise RuntimeError(f"Seedream 请求失败：{last_error}") from last_error


def generate_batch(
    request: ImageBatchRequest,
    *,
    model_id: str = SEEDREAM_MODEL_ID,
) -> None:
    """Generate one durable local PNG for every persisted candidate request."""
    request.result_path.unlink(missing_ok=True)
    write_json(request.batch_path, list(request.jobs))
    results: list[dict] = []
    failed = 0
    client = SeedreamClient(project_id=request.project_id, model_id=model_id)
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
