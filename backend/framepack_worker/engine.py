from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Callable


class FramePackCancelled(RuntimeError):
    pass


class FramePackEngine:
    def __init__(self) -> None:
        self.model_id = os.environ.get(
            "FRAMEPACK_MODEL_ID", "lllyasviel/FramePack_F1_I2V_HY_20250503"
        )
        self.base_model_id = os.environ.get(
            "FRAMEPACK_BASE_MODEL_ID", "hunyuanvideo-community/HunyuanVideo"
        )
        self.sampling_type = os.environ.get("FRAMEPACK_SAMPLING_TYPE", "vanilla")
        self.allow_download = os.environ.get("FRAMEPACK_ALLOW_MODEL_DOWNLOAD", "0") == "1"
        self.cpu_offload = os.environ.get("FRAMEPACK_CPU_OFFLOAD", "1") == "1"
        self.pipeline = None
        self.torch = None
        self.export_to_video = None
        self.load_image = None

    def load(self) -> None:
        import torch
        from diffusers import (
            HunyuanVideoFramepackPipeline,
            HunyuanVideoFramepackTransformer3DModel,
        )
        from diffusers.hooks import apply_group_offloading
        from diffusers.utils import export_to_video, load_image
        from transformers import SiglipImageProcessor, SiglipVisionModel

        local_only = not self.allow_download
        transformer = HunyuanVideoFramepackTransformer3DModel.from_pretrained(
            self.model_id,
            torch_dtype=torch.bfloat16,
            local_files_only=local_only,
        )
        feature_extractor = SiglipImageProcessor.from_pretrained(
            "lllyasviel/flux_redux_bfl",
            subfolder="feature_extractor",
            local_files_only=local_only,
        )
        image_encoder = SiglipVisionModel.from_pretrained(
            "lllyasviel/flux_redux_bfl",
            subfolder="image_encoder",
            torch_dtype=torch.float16,
            local_files_only=local_only,
        )
        pipeline = HunyuanVideoFramepackPipeline.from_pretrained(
            self.base_model_id,
            transformer=transformer,
            feature_extractor=feature_extractor,
            image_encoder=image_encoder,
            torch_dtype=torch.float16,
            local_files_only=local_only,
        )
        pipeline.vae.enable_tiling()
        if self.cpu_offload:
            onload_device = torch.device("cuda")
            offload_device = torch.device("cpu")
            for component in (
                pipeline.text_encoder,
                pipeline.text_encoder_2,
                pipeline.transformer,
            ):
                apply_group_offloading(
                    component,
                    onload_device=onload_device,
                    offload_device=offload_device,
                    offload_type="leaf_level",
                    use_stream=True,
                    low_cpu_mem_usage=True,
                )
            pipeline.image_encoder.to(onload_device)
            pipeline.vae.to(onload_device)
        else:
            pipeline.to("cuda")
        self.pipeline = pipeline
        self.torch = torch
        self.export_to_video = export_to_video
        self.load_image = load_image

    def generate(
        self,
        request,
        cancel_event: threading.Event,
        on_progress: Callable[[int, int], None],
    ) -> Path:
        if self.pipeline is None or self.torch is None:
            raise RuntimeError("FramePack 模型尚未加载")
        input_path = _safe_path(request.input_image, must_exist=True)
        output_path = _safe_path(request.output_path, must_exist=False)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.unlink(missing_ok=True)
        num_frames = _framepack_frame_count(request.duration, request.fps)

        def callback(_pipeline, step: int, _timestep, callback_kwargs):
            if cancel_event.is_set():
                raise FramePackCancelled("FramePack task cancelled")
            on_progress(min(95, round((step + 1) / request.steps * 95)), 0)
            return callback_kwargs

        generator = self.torch.Generator(device="cpu").manual_seed(request.seed)
        try:
            frames = self.pipeline(
                image=self.load_image(str(input_path)),
                prompt=request.prompt,
                height=request.height,
                width=request.width,
                num_frames=num_frames,
                latent_window_size=request.latent_window_size,
                num_inference_steps=request.steps,
                guidance_scale=request.guidance_scale,
                generator=generator,
                sampling_type=self.sampling_type,
                callback_on_step_end=callback,
            ).frames[0]
        finally:
            if self.torch.cuda.is_available():
                self.torch.cuda.empty_cache()
        if cancel_event.is_set():
            raise FramePackCancelled("FramePack task cancelled")
        on_progress(97, len(frames))
        self.export_to_video(frames, str(output_path), fps=request.fps)
        on_progress(100, len(frames))
        return output_path

    def gpu_info(self) -> tuple[str | None, float | None]:
        if self.torch is None or not self.torch.cuda.is_available():
            return None, None
        free, _total = self.torch.cuda.mem_get_info()
        return self.torch.cuda.get_device_name(0), round(free / 1024**3, 2)


def _framepack_frame_count(duration: float, fps: int) -> int:
    requested = max(9, round(duration * fps))
    return max(9, 4 * round((requested - 3) / 4) + 3)


def _safe_path(value: str, must_exist: bool) -> Path:
    path = Path(value).expanduser().resolve()
    allowed_value = os.environ.get("FRAMEPACK_ALLOWED_ROOT", "").strip()
    if not allowed_value:
        raise RuntimeError("FRAMEPACK_ALLOWED_ROOT 未配置")
    allowed = Path(allowed_value).expanduser().resolve()
    try:
        path.relative_to(allowed)
    except ValueError as exc:
        raise ValueError(f"FramePack 路径超出允许目录：{path}") from exc
    if must_exist and not path.is_file():
        raise ValueError(f"FramePack 输入图片不存在：{path}")
    return path
