import json

import httpx

from app.config import Settings, get_settings
from app.infrastructure import process_runner as task_control


class DeepSeekClient:
    def __init__(self, settings: Settings | None = None, project_id: str | None = None) -> None:
        self.settings = settings or get_settings()
        self.project_id = project_id

    @property
    def name(self) -> str:
        return "llm.deepseek"

    @property
    def model(self) -> str:
        return self.settings.deepseek_model

    def chat_json(self, system_prompt: str, user_prompt: str) -> dict:
        if not self.settings.deepseek_api_key.strip():
            raise ValueError("系统尚未配置 DeepSeek API Key")
        endpoint = self.settings.deepseek_base_url.rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint = f"{endpoint}/chat/completions"
        payload = {
            "model": self.settings.deepseek_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "max_tokens": self.settings.deepseek_max_tokens,
            "stream": False,
        }
        last_error: Exception | None = None
        for _attempt in range(self.settings.deepseek_retry_count + 1):
            if self.project_id:
                task_control.check_cancelled(self.project_id)
            client = httpx.Client(timeout=self.settings.deepseek_timeout_seconds)
            if self.project_id:
                task_control.register_cancel_callback(self.project_id, client.close)
            try:
                response = client.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {self.settings.deepseek_api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                if self.project_id:
                    task_control.check_cancelled(self.project_id)
                response.raise_for_status()
                data = response.json()
                choice = data["choices"][0]
                if choice.get("finish_reason") == "length":
                    raise RuntimeError("DeepSeek 输出被 max_tokens 截断")
                content = choice["message"].get("content")
                if not isinstance(content, str) or not content.strip():
                    raise RuntimeError("DeepSeek 返回了空内容")
                parsed = json.loads(content)
                if not isinstance(parsed, dict):
                    raise RuntimeError("DeepSeek 返回的 JSON 根节点必须是对象")
                return parsed
            except task_control.TaskCancelledError:
                raise
            except (httpx.HTTPError, OSError, KeyError, IndexError, TypeError, json.JSONDecodeError, RuntimeError) as exc:
                last_error = exc
            finally:
                if self.project_id:
                    task_control.register_cancel_callback(self.project_id, None)
                client.close()
        raise RuntimeError(f"DeepSeek 请求失败：{last_error}") from last_error
