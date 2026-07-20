from typing import Literal

from pydantic import BaseModel, Field


MotionPreset = Literal[
    "auto",
    "static",
    "slow_zoom_in",
    "slow_zoom_out",
    "pan_left_to_right",
    "pan_right_to_left",
    "pan_top_to_bottom",
    "pan_bottom_to_top",
    "diagonal_top_left",
    "diagonal_top_right",
    "portrait_push_in",
    "environment_pull_out",
    "subtle_breathing",
    "random_safe",
    # Compatibility with assignments created before named presets were added.
    "zoom_in",
    "zoom_out",
    "pan_left",
    "pan_right",
    "still",
]


class VideoRenderConfig(BaseModel):
    width: int = Field(default=1920, ge=640, le=7680, multiple_of=2)
    height: int = Field(default=1080, ge=360, le=4320, multiple_of=2)
    fps: int = Field(default=30, ge=1, le=120)
    video_codec: str = Field(default="libx264", min_length=1, max_length=40)
    pixel_format: str = Field(default="yuv420p", min_length=1, max_length=40)
    crf: int = Field(default=20, ge=0, le=51)
    preset: str = Field(default="veryfast", min_length=1, max_length=40)


class SceneRenderPolicy(BaseModel):
    provider: Literal["ffmpeg"] = "ffmpeg"
    duration_tolerance_frames: int = Field(default=1, ge=0, le=5)
    verify_no_audio: bool = True
    transition_enabled: bool = False
    transition_duration: float = Field(default=0.3, ge=0, le=2)


class ProjectRenderConfig(BaseModel):
    video: VideoRenderConfig = Field(default_factory=VideoRenderConfig)
    policy: SceneRenderPolicy = Field(default_factory=SceneRenderPolicy)

