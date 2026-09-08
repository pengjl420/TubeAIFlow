from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field


class ImageQCResult(BaseModel):
    semantic_match: int = Field(ge=1, le=5)
    random_text: bool
    watermark: bool
    unapproved_logo: bool = False
    approved: bool


class LLMProvider(Protocol):
    def generate_json(self, prompt: str, schema: dict, options: dict | None = None) -> dict: ...


class ImageProvider(Protocol):
    def generate(self, request: dict) -> list[dict]: ...


class VisionProvider(Protocol):
    def inspect(self, image_path: str, request: dict) -> dict: ...


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


class MockImageProvider:
    name = "mock-image"

    def generate(self, request: dict) -> list[dict]:
        count = int(request.get("candidates", 1))
        base_seed = int(request.get("seed", 0))
        return [
            {
                "generation_id": _stable_digest({"request": request, "index": index})[:16],
                "seed": base_seed + index,
                "status": "mocked",
                "path": f"mock://image/{base_seed + index}.png",
            }
            for index in range(count)
        ]


class MockVisionProvider:
    name = "mock-vision"

    def inspect(self, image_path: str, request: dict) -> dict:
        score = 4 + (int(_stable_digest({"path": image_path, "request": request})[:2], 16) % 2)
        return {
            "semantic_match": score,
            "random_text": False,
            "watermark": False,
            "approved": True,
        }


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
            content = "".join(str(item.get("text") or "") for item in content if isinstance(item, dict))
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


class ComfyUIImageProvider:
    name = "comfyui"

    def __init__(
        self,
        base_url: str,
        workflow_path: Path,
        output_dir: Path,
        *,
        timeout_seconds: float = 900,
        poll_seconds: float = 1,
    ):
        self.base_url = base_url.rstrip("/")
        self.workflow_path = workflow_path.resolve()
        self.output_dir = output_dir.resolve()
        self.timeout_seconds = timeout_seconds
        self.poll_seconds = poll_seconds

    def generate(self, request: dict) -> list[dict]:
        workflow = json.loads(self.workflow_path.read_text(encoding="utf-8"))
        patched = self._patch(workflow, request)
        response = httpx.post(
            f"{self.base_url}/prompt", json={"prompt": patched}, timeout=30
        )
        response.raise_for_status()
        prompt_id = response.json()["prompt_id"]
        history = self._wait(prompt_id)
        results = []
        self.output_dir.mkdir(parents=True, exist_ok=True)
        for node in history.get("outputs", {}).values():
            for image in node.get("images", []):
                image_response = httpx.get(
                    f"{self.base_url}/view",
                    params={
                        "filename": image["filename"],
                        "subfolder": image.get("subfolder", ""),
                        "type": image.get("type", "output"),
                    },
                    timeout=60,
                )
                image_response.raise_for_status()
                destination = self.output_dir / f"{request['visual_id']}_{len(results) + 1:02d}.png"
                destination.write_bytes(image_response.content)
                results.append(
                    {
                        "generation_id": f"{prompt_id}:{len(results) + 1}",
                        "seed": int(request.get("seed", 0)) + len(results),
                        "status": "completed",
                        "path": str(destination),
                    }
                )
        if not results:
            raise RuntimeError(f"ComfyUI prompt {prompt_id} completed without image output")
        return results

    def _wait(self, prompt_id: str) -> dict:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            response = httpx.get(f"{self.base_url}/history/{prompt_id}", timeout=30)
            response.raise_for_status()
            item = response.json().get(prompt_id)
            if item:
                status = item.get("status", {})
                if status.get("status_str") == "error":
                    raise RuntimeError(f"ComfyUI prompt failed: {status}")
                if item.get("outputs"):
                    return item
            time.sleep(self.poll_seconds)
        raise TimeoutError(f"ComfyUI prompt timed out after {self.timeout_seconds}s")

    @classmethod
    def _patch(cls, value: Any, request: dict) -> Any:
        replacements = {
            "{{PROMPT}}": str(request.get("prompt", "")),
            "{{NEGATIVE_PROMPT}}": str(request.get("negative_prompt", "")),
            "{{SEED}}": int(request.get("seed", 0)),
            "{{WIDTH}}": int(request.get("width", 1344)),
            "{{HEIGHT}}": int(request.get("height", 768)),
            "{{BATCH_SIZE}}": int(request.get("candidates", 1)),
            "{{OUTPUT_PREFIX}}": str(request.get("visual_id", "visual")),
        }
        if isinstance(value, dict):
            return {key: cls._patch(item, request) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._patch(item, request) for item in value]
        return replacements.get(value, value)


class Qwen3VLVisionProvider:
    name = "qwen3-vl"

    def __init__(
        self,
        model_dir: Path,
        *,
        max_new_tokens: int = 512,
        semantic_match_min: int = 4,
        reject_random_text: bool = True,
        reject_watermark: bool = True,
        reject_unapproved_logo: bool = True,
    ):
        self.model_dir = model_dir.resolve()
        self.max_new_tokens = max_new_tokens
        self.semantic_match_min = semantic_match_min
        self.reject_random_text = reject_random_text
        self.reject_watermark = reject_watermark
        self.reject_unapproved_logo = reject_unapproved_logo
        self._model = None
        self._processor = None

    def inspect(self, image_path: str, request: dict) -> dict:
        from PIL import Image

        self._load()
        image = Image.open(image_path).convert("RGB")
        prompt = (
            "Inspect this generated editorial image against the claim below. Return JSON only with "
            "semantic_match (integer 1-5), random_text (boolean), watermark (boolean), "
            "unapproved_logo (boolean), and approved (boolean).\nCLAIM:\n"
            + str(request.get("claim") or "")
        )
        messages = [{"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": prompt}]}]
        inputs = self._processor.apply_chat_template(
            messages,
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
        ).to(self._model.device)
        outputs = self._model.generate(**inputs, max_new_tokens=self.max_new_tokens, do_sample=False)
        generated = outputs[0][inputs["input_ids"].shape[-1] :]
        text = self._processor.decode(generated, skip_special_tokens=True).strip()
        if text.startswith("```"):
            text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            result = ImageQCResult.model_validate_json(text)
        except ValueError as exc:
            raise ValueError("Qwen3-VL returned invalid QC JSON") from exc
        result.approved = (
            result.semantic_match >= self.semantic_match_min
            and not (self.reject_random_text and result.random_text)
            and not (self.reject_watermark and result.watermark)
            and not (self.reject_unapproved_logo and result.unapproved_logo)
        )
        return result.model_dump(mode="json")

    def _load(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoProcessor, Qwen3VLForConditionalGeneration

        if not (self.model_dir / "config.json").is_file():
            raise FileNotFoundError(f"Incomplete Qwen3-VL model at {self.model_dir}")
        self._processor = AutoProcessor.from_pretrained(
            self.model_dir, local_files_only=True
        )
        self._model = Qwen3VLForConditionalGeneration.from_pretrained(
            self.model_dir,
            local_files_only=True,
            device_map="auto",
            dtype=torch.bfloat16,
        )
        self._model.eval()
