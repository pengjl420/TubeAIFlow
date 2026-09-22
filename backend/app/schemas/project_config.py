from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProjectConfig(BaseModel):
    """Typed core of the extensible project configuration envelope.

    Unknown keys are retained for provider and forward-compatible settings.  Stable
    workflow fields are validated here instead of being interpreted independently by
    every service.
    """

    model_config = ConfigDict(extra="allow")

    tts_engine: str = Field(default="index_tts", min_length=1)
    segmentation_mode: Literal["newline", "ai"] = "newline"
    storyboard_mode: Literal["ai", "segments"] = "ai"
    image_provider_id: str = "image.local_sdxl"
    visual_enrichment_mode: Literal["auto", "advanced", "basic"] = "auto"
    visual_generation_mode: str = "curated"
    visual_enrichment_config_path: str = "config/production_5060ti.yaml"
    video_mode: Literal["none", "landscape", "ai_generated_images", "ai_landscape_mix"] = "none"
    # Keep legacy values readable so existing project descriptors still migrate/load.
    # New writes are normalized to prproj by project_service.
    video_output_format: Literal["mp4", "fcpxml", "prproj", "editable_both"] = "prproj"
    include_video: bool = False
    output_filename: str | None = None
    project_directory_name: str | None = None
    voice_language: str = "zh-CN"
    fps: int = Field(default=30, ge=1, le=120)
    width: int = Field(default=1920, ge=640, le=7680, multiple_of=2)
    height: int = Field(default=1080, ge=360, le=4320, multiple_of=2)
    aspect_ratio: str = "16:9"
    locked: bool = False
