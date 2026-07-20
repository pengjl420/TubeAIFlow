from typing import Literal

from pydantic import BaseModel, Field


FramePackJobStatus = Literal[
    "queued", "loading", "sampling", "encoding", "completed", "failed", "cancelled"
]


class FramePackJobRequest(BaseModel):
    job_id: str = Field(min_length=1, max_length=180)
    input_image: str = Field(min_length=1)
    output_path: str = Field(min_length=1)
    prompt: str = Field(min_length=1, max_length=4000)
    seed: int = 31337
    duration: float = Field(default=5.0, ge=1.0, le=8.0)
    width: int = Field(default=832, ge=256, le=1920, multiple_of=16)
    height: int = Field(default=480, ge=256, le=1088, multiple_of=16)
    fps: int = Field(default=30, ge=1, le=60)
    steps: int = Field(default=25, ge=1, le=100)
    latent_window_size: int = Field(default=9, ge=1, le=33)
    guidance_scale: float = Field(default=9.0, ge=1, le=32)
    mp4_crf: int = Field(default=16, ge=0, le=51)


class FramePackJobRead(BaseModel):
    job_id: str
    status: FramePackJobStatus
    progress: int = Field(default=0, ge=0, le=100)
    generated_frames: int = 0
    elapsed_seconds: float = 0
    output_path: str | None = None
    error: str | None = None


class FramePackHealth(BaseModel):
    status: Literal["starting", "loading_model", "ready", "busy", "unavailable", "error"]
    model_loaded: bool = False
    gpu: str | None = None
    free_vram_gb: float | None = None
    current_job_id: str | None = None
    error: str | None = None

