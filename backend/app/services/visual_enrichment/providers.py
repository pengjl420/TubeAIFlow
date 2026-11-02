from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Protocol

import httpx


class LLMProvider(Protocol):
    def generate_json(self, prompt: str, schema: dict, options: dict | None = None) -> dict: ...


class EmbeddingProvider(Protocol):
    model_id: str

    def encode(self, texts: list[str]) -> list[list[float]]: ...


def _stable_digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class MockLLMProvider:
    """Deterministic structured fixture provider; never imports an AI SDK."""

    name = "mock-llm"

    def generate_json(self, prompt: str, schema: dict, options: dict | None = None) -> dict:
        properties = schema.get("properties", {})
        if "chapter_title" in properties:
            try:
                payload = json.loads(prompt)
                text = str(payload.get("text") or "")
            except (json.JSONDecodeError, AttributeError):
                text = prompt
            return {
                "chapter_title": "Mock chapter",
                "summary": text[:240],
                "main_claims": [text[:120]] if text else [],
                "entities": [],
                "narrative_mode": "explanation",
                "emotion_curve": "steady",
            }
        if "visual_type" in properties and "brief" in properties:
            try:
                payload = json.loads(prompt)
                text = str(payload.get("voiceover") or "")
                suggested = str(payload.get("suggested_type") or "conceptual_illustration")
            except (json.JSONDecodeError, AttributeError):
                text = prompt
                suggested = "conceptual_illustration"
            return {
                "visual_type": suggested,
                "brief": {
                    "subject": text[:80] or "central narrated concept",
                    "action": "shows one clear visual relationship",
                    "environment": "documentary editorial setting",
                    "semantic_message": text or "central narrated claim",
                    "composition": "wide composition with one focal hierarchy",
                    "mood": "documentary",
                    "must_include": [],
                    "must_avoid": ["visible logos", "watermark", "random text"],
                },
            }
        digest = _stable_digest({"prompt": prompt, "schema": schema, "options": options or {}})
        return {"mock_id": digest[:16], "summary": prompt.strip()[:160]}


class MockEmbeddingProvider:
    model_id = "deterministic-mock-embedding-v1"

    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for value in texts:
            digest = hashlib.sha256(value.encode("utf-8")).digest()
            raw = [(byte - 127.5) / 127.5 for byte in digest]
            magnitude = sum(item * item for item in raw) ** 0.5 or 1
            vectors.append([item / magnitude for item in raw])
        return vectors


class LlamaCppLLMProvider:
    name = "llamacpp"

    def __init__(
        self,
        base_url: str,
        *,
        model: str = "qwen3-8b-q4_k_m",
        timeout_seconds: float = 180,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def generate_json(self, prompt: str, schema: dict, options: dict | None = None) -> dict:
        settings = options or {}
        response = httpx.post(
            f"{self.base_url}/v1/chat/completions",
            json={
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Return one JSON object that strictly matches the supplied schema. "
                            "Do not use Markdown fences or add commentary. /no_think"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": float(settings.get("temperature", 0.3)),
                "top_p": float(settings.get("top_p", 0.8)),
                "max_tokens": int(settings.get("max_tokens", 4096)),
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "structured_output", "strict": True, "schema": schema},
                },
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(
                str(item.get("text") or "") for item in content if isinstance(item, dict)
            )
        try:
            result = json.loads(str(content).strip())
        except json.JSONDecodeError as exc:
            raise ValueError("llama.cpp returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise ValueError("llama.cpp structured response must be a JSON object")
        return result

    def health(self) -> dict:
        response = httpx.get(f"{self.base_url}/health", timeout=10)
        response.raise_for_status()
        return response.json()


class BgeM3OnnxEmbeddingProvider:
    model_id = "BAAI/bge-m3-onnx"

    def __init__(self, model_dir: Path, *, max_length: int = 512):
        self.model_dir = model_dir.resolve()
        self.max_length = max_length
        self._tokenizer = None
        self._session = None

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        import numpy as np

        self._load()
        self._tokenizer.enable_truncation(max_length=self.max_length)
        self._tokenizer.enable_padding()
        encoded = self._tokenizer.encode_batch(texts)
        input_ids = np.asarray([item.ids for item in encoded], dtype=np.int64)
        attention_mask = np.asarray([item.attention_mask for item in encoded], dtype=np.int64)
        sentence_embeddings = self._session.run(
            ["sentence_embedding"],
            {"input_ids": input_ids, "attention_mask": attention_mask},
        )[0]
        norms = np.linalg.norm(sentence_embeddings, axis=1, keepdims=True)
        normalized = sentence_embeddings / np.clip(norms, 1e-12, None)
        return normalized.astype(np.float32).tolist()

    def _load(self) -> None:
        if self._session is not None:
            return
        import onnxruntime as ort
        from tokenizers import Tokenizer

        onnx_dir = self.model_dir / "onnx"
        model_path = onnx_dir / "model.onnx"
        tokenizer_path = onnx_dir / "tokenizer.json"
        if not model_path.is_file() or not tokenizer_path.is_file():
            raise FileNotFoundError(f"Incomplete BGE-M3 ONNX model at {self.model_dir}")
        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self._session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])


