from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from typing import Protocol

from app.config import get_settings
from app.infrastructure.atomic_files import write_json_atomic
from app.integrations.llm.deepseek import DeepSeekClient


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
    if not settings.deepseek_api_key.strip():
        raise ValueError("AI 分段与分镜需要先配置 DeepSeek API Key")
    provider: JSONLLMProvider = DeepSeekClient(settings, project_id)
    if settings.storyboard_llm_cache_enabled:
        provider = CachedLLMClient(
            provider,
            settings.workspace_dir / "cache" / "llm" / "storyboard",
        )
    return provider
