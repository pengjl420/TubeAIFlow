from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Sequence

from app.config import get_settings
from app.infrastructure import gpu_resource


MODEL_NAME = "Qwen/Qwen3-VL-Embedding-2B"
VECTOR_DIMENSIONS = 2048
_MODEL_LOCK = RLock()
_RUNTIME = None
_RUNTIME_SIGNATURE: tuple | None = None


def embed_text(value: str) -> list[float]:
    return embed_media(value, ())


def embed_media(value: str, image_paths: Sequence[str | Path]) -> list[float]:
    text = str(value or "").strip()
    paths = _existing_images(image_paths)
    if not text and not paths:
        return [0.0] * VECTOR_DIMENSIONS
    with gpu_resource.exclusive_gpu("vision-embedding"):
        gpu_resource.defer_cleanup("vision-embedding-model", release_model)
        return _get_runtime().embed(text, paths)


def release_model() -> None:
    """Release the embedding model before another local VLM needs the GPU."""
    global _RUNTIME, _RUNTIME_SIGNATURE
    with _MODEL_LOCK:
        _RUNTIME = None
        _RUNTIME_SIGNATURE = None
        try:
            import gc
            import torch

            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass


def _existing_images(values: Sequence[str | Path]) -> list[Path]:
    paths: list[Path] = []
    for value in values:
        path = Path(value).expanduser().resolve()
        if not path.is_file():
            raise RuntimeError(f"Embedding keyframe does not exist: {path}")
        paths.append(path)
    return paths


def _get_runtime():
    global _RUNTIME, _RUNTIME_SIGNATURE
    settings = get_settings()
    model_dir = settings.vision_embedding_model_dir
    if model_dir is None:
        raise RuntimeError("vision_embedding_model_dir is not configured")
    model_dir = model_dir.expanduser().resolve()
    if not (model_dir / "config.json").is_file():
        raise RuntimeError(f"Qwen3-VL embedding model is incomplete: {model_dir}")
    signature = (
        str(model_dir),
        settings.vision_embedding_device,
        settings.vision_embedding_dtype,
        settings.vision_embedding_max_images,
        settings.vision_embedding_max_pixels,
        settings.vision_embedding_instruction,
    )
    with _MODEL_LOCK:
        if _RUNTIME is None or _RUNTIME_SIGNATURE != signature:
            _RUNTIME = _Qwen3VLEmbeddingRuntime(
                model_dir=model_dir,
                device=settings.vision_embedding_device,
                dtype=settings.vision_embedding_dtype,
                max_images=settings.vision_embedding_max_images,
                max_pixels=settings.vision_embedding_max_pixels,
                instruction=settings.vision_embedding_instruction,
            )
            _RUNTIME_SIGNATURE = signature
        return _RUNTIME


class _Qwen3VLEmbeddingRuntime:
    def __init__(
        self,
        model_dir: Path,
        device: str,
        dtype: str,
        max_images: int,
        max_pixels: int,
        instruction: str,
    ) -> None:
        try:
            import torch
            from transformers import AutoProcessor, Qwen3VLForConditionalGeneration
        except ImportError as exc:
            raise RuntimeError(
                "Qwen3-VL embedding dependencies are missing; install backend/requirements.txt"
            ) from exc

        if device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("CUDA is not available for Qwen3-VL embedding")
        torch_dtype = {
            "bfloat16": torch.bfloat16,
            "float16": torch.float16,
            "float32": torch.float32,
        }[dtype]
        if device == "cpu" and torch_dtype != torch.float32:
            torch_dtype = torch.float32

        self.torch = torch
        self.device = torch.device(device)
        self.max_images = max_images
        self.max_pixels = max_pixels
        self.instruction = instruction
        self.inference_lock = RLock()
        full_model = Qwen3VLForConditionalGeneration.from_pretrained(
            str(model_dir),
            dtype=torch_dtype,
            attn_implementation="sdpa",
            local_files_only=True,
            low_cpu_mem_usage=True,
        )
        self.model = full_model.model.to(self.device).eval()
        self.processor = AutoProcessor.from_pretrained(
            str(model_dir),
            padding_side="right",
            local_files_only=True,
        )

    def embed(self, text: str, image_paths: Sequence[Path]) -> list[float]:
        with self.inference_lock:
            return self._embed(text, image_paths)

    def _embed(self, text: str, image_paths: Sequence[Path]) -> list[float]:
        try:
            from qwen_vl_utils.vision_process import process_vision_info
        except ImportError as exc:
            raise RuntimeError(
                "qwen-vl-utils is required for Qwen3-VL embedding"
            ) from exc

        selected_images = _sample_images(image_paths, self.max_images)
        content = [
            {
                "type": "image",
                "image": f"file://{path}",
                "min_pixels": 4096,
                "max_pixels": self.max_pixels,
            }
            for path in selected_images
        ]
        content.append({"type": "text", "text": text or "NULL"})
        conversations = [
            [
                {
                    "role": "system",
                    "content": [{"type": "text", "text": self.instruction}],
                },
                {"role": "user", "content": content},
            ]
        ]
        prompt = self.processor.apply_chat_template(
            conversations,
            add_generation_prompt=True,
            tokenize=False,
        )
        images, video_inputs, video_kwargs = process_vision_info(
            conversations,
            image_patch_size=16,
            return_video_metadata=True,
            return_video_kwargs=True,
        )
        if video_inputs is not None:
            videos, video_metadata = zip(*video_inputs)
            videos, video_metadata = list(videos), list(video_metadata)
        else:
            videos, video_metadata = None, None
        inputs = self.processor(
            text=prompt,
            images=images,
            videos=videos,
            video_metadata=video_metadata,
            padding=True,
            truncation=True,
            max_length=8192,
            do_resize=False,
            return_tensors="pt",
            **video_kwargs,
        )
        inputs = {
            name: value.to(self.device) if hasattr(value, "to") else value
            for name, value in inputs.items()
        }
        with self.torch.inference_mode():
            outputs = self.model(**inputs, use_cache=False, return_dict=True)
            attention_mask = inputs["attention_mask"]
            last_positions = attention_mask.long().sum(dim=1) - 1
            rows = self.torch.arange(outputs.last_hidden_state.shape[0], device=self.device)
            embedding = outputs.last_hidden_state[rows, last_positions]
            embedding = self.torch.nn.functional.normalize(embedding.float(), p=2, dim=-1)
        return embedding[0].cpu().tolist()


def _sample_images(paths: Sequence[Path], limit: int) -> list[Path]:
    if len(paths) <= limit:
        return list(paths)
    if limit == 1:
        return [paths[len(paths) // 2]]
    return [paths[round(index * (len(paths) - 1) / (limit - 1))] for index in range(limit)]
