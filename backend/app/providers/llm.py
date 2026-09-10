from __future__ import annotations

import hashlib
import inspect
import json
import logging
from pathlib import Path
from typing import Protocol

import httpx

from app.config import Settings, get_settings
from app.infrastructure import process_runner as task_control
from app.infrastructure.atomic_files import write_json_atomic
from app.integrations.llm.deepseek import DeepSeekClient


logger = logging.getLogger(__name__)


class JSONLLMProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str: ...

    def chat_json(self, system_prompt: str, user_prompt: str, **kwargs) -> dict: ...


def invoke_json(
    provider: JSONLLMProvider,
    system_prompt: str,
    user_prompt: str,
    *,
    schema: dict | None = None,
    task: str = "generic",
) -> dict:
    """Call new providers with metadata while retaining extension/test compatibility."""
    parameters = inspect.signature(provider.chat_json).parameters
    kwargs = {}
    if "schema" in parameters or any(
        item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters.values()
    ):
        kwargs["schema"] = schema
        kwargs["task"] = task
    return provider.chat_json(system_prompt, user_prompt, **kwargs)


class LlamaCppClient:
    name = "llm.local_qwen"

    def __init__(self, settings: Settings, project_id: str | None = None) -> None:
        self.settings = settings
        self.project_id = project_id
        self.model = settings.local_llm_model

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        schema: dict | None = None,
        task: str = "generic",
    ) -> dict:
        if self.project_id:
            task_control.check_cancelled(self.project_id)
        endpoint = self.settings.local_llm_base_url.rstrip("/")
        if endpoint.endswith("/v1"):
            endpoint = f"{endpoint}/chat/completions"
        elif not endpoint.endswith("/v1/chat/completions"):
            endpoint = f"{endpoint}/v1/chat/completions"
        response_format = {"type": "json_object"}
        if schema:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": task.replace("-", "_")[:48],
                    "strict": True,
                    "schema": schema,
                },
            }
        client = httpx.Client(timeout=self.settings.local_llm_timeout_seconds)
        if self.project_id:
            task_control.register_cancel_callback(self.project_id, client.close)
        try:
            response = client.post(
                endpoint,
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": system_prompt + "\nReturn JSON only. /no_think",
                        },
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.2,
                    "top_p": 0.8,
                    "max_tokens": self.settings.local_llm_max_tokens,
                    "response_format": response_format,
                    "stream": False,
                },
            )
            if self.project_id:
                task_control.check_cancelled(self.project_id)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "".join(
                    str(item.get("text") or "") for item in content if isinstance(item, dict)
                )
            payload = json.loads(str(content).strip())
            if not isinstance(payload, dict):
                raise ValueError("Local LLM JSON root must be an object")
            return payload
        finally:
            if self.project_id:
                task_control.register_cancel_callback(self.project_id, None)
            client.close()


class HybridLLMClient:
    """Prefer local inference and escalate only uncertain/high-risk storyboard output."""

    name = "llm.hybrid"

    def __init__(
        self,
        local: JSONLLMProvider,
        cloud: JSONLLMProvider | None,
        settings: Settings,
    ) -> None:
        self.local = local
        self.cloud = cloud
        self.settings = settings
        self.model = f"{local.model}+{cloud.model if cloud else 'no-cloud'}"
        self.routes: list[str] = []

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        schema: dict | None = None,
        task: str = "generic",
    ) -> dict:
        if task == "storyboard-repair" and self.cloud is not None:
            self.routes.append("cloud:schema-repair")
            return invoke_json(self.cloud, system_prompt, user_prompt, schema=schema, task=task)
        try:
            local_payload = invoke_json(
                self.local, system_prompt, user_prompt, schema=schema, task=task
            )
            if not task.startswith(("storyboard", "scene-grouping")) or not self._needs_cloud(
                local_payload, task
            ):
                self.routes.append("local")
                return local_payload
            if self.cloud is None:
                self.routes.append("local:cloud-unavailable")
                return local_payload
            self.routes.append("cloud:quality-escalation")
        except task_control.TaskCancelledError:
            raise
        except (httpx.HTTPError, OSError, KeyError, TypeError, ValueError, RuntimeError) as exc:
            if self.cloud is None:
                raise
            logger.warning("Local LLM unavailable; falling back to cloud: %s", exc)
            self.routes.append("cloud:local-fallback")
        return invoke_json(self.cloud, system_prompt, user_prompt, schema=schema, task=task)

    def _needs_cloud(self, payload: dict, task: str) -> bool:
        if task.startswith("scene-grouping"):
            groups = payload.get("groups")
            if not isinstance(groups, list) or not groups:
                return True
            return any(
                not isinstance(group, dict)
                or not isinstance(group.get("confidence"), (int, float))
                or group["confidence"] < self.settings.storyboard_cloud_confidence_threshold
                for group in groups
            )
        scenes = payload.get("scenes")
        if not isinstance(scenes, list) or not scenes:
            return True
        threshold = self.settings.storyboard_cloud_confidence_threshold
        risk_threshold = self.settings.storyboard_cloud_identity_risk_threshold
        for scene in scenes:
            if not isinstance(scene, dict):
                return True
            confidence = scene.get("confidence")
            identity_risk = scene.get("identity_risk", 0)
            if not isinstance(confidence, (int, float)) or confidence < threshold:
                return True
            if isinstance(identity_risk, (int, float)) and identity_risk >= risk_threshold:
                return True
        return False


class CachedLLMClient:
    def __init__(self, provider: JSONLLMProvider, cache_dir: Path) -> None:
        self.provider = provider
        self.cache_dir = cache_dir
        self.name = provider.name
        self.model = provider.model
        self._cache_routes: list[str] = []

    @property
    def routes(self) -> list[str]:
        return [*getattr(self.provider, "routes", []), *self._cache_routes]

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        schema: dict | None = None,
        task: str = "generic",
    ) -> dict:
        digest = hashlib.sha256(
            json.dumps(
                {
                    "provider": self.provider.name,
                    "model": self.provider.model,
                    "system": system_prompt,
                    "user": user_prompt,
                    "schema": schema,
                    "task": task,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        path = self.cache_dir / f"{digest}.json"
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                self._cache_routes.append(f"cache:{task}")
                return payload
        payload = invoke_json(self.provider, system_prompt, user_prompt, schema=schema, task=task)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(path, payload)
        return payload


def build_storyboard_llm(project_id: str | None = None) -> JSONLLMProvider:
    settings = get_settings()
    local = LlamaCppClient(settings, project_id)
    cloud = DeepSeekClient(settings, project_id) if settings.deepseek_api_key.strip() else None
    if settings.storyboard_llm_strategy == "local":
        provider: JSONLLMProvider = local
    elif settings.storyboard_llm_strategy == "cloud":
        if cloud is None:
            raise ValueError("云端分镜模式需要先配置 DeepSeek API Key")
        provider = cloud
    else:
        provider = HybridLLMClient(local, cloud, settings)
    if settings.storyboard_llm_cache_enabled:
        provider = CachedLLMClient(
            provider,
            settings.workspace_dir / "cache" / "llm" / "storyboard",
        )
    return provider
