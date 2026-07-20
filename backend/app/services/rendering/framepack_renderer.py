from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from app.config import Settings
from app.infrastructure import gpu_resource
from app.infrastructure.ffmpeg import run_ffmpeg
from app.integrations.framepack.client import FramePackClient, FramePackError
from app.integrations.framepack.schemas import FramePackJobRequest
from app.models.project import Project
from app.models.storyboard import VisualScene
from app.schemas.render import ProjectRenderConfig
from app.schemas.storyboard import StoryboardContent


def render_framepack_scene(
    project: Project,
    scene: VisualScene,
    source_path: Path,
    output_path: Path,
    settings: Settings,
    render_config: ProjectRenderConfig,
) -> dict:
    runtime_dir = settings.workspace_dir / ".runtime" / "framepack" / project.id / scene.id.replace(":", "_")
    runtime_dir.mkdir(parents=True, exist_ok=True)
    staged_input = runtime_dir / f"input{source_path.suffix.lower()}"
    raw_output = runtime_dir / "raw.mp4"
    shutil.copyfile(source_path, staged_input)
    storyboard = _storyboard(scene)
    duration = (scene.end_ms - scene.start_ms) / 1000
    client = FramePackClient(settings)
    last_error: Exception | None = None
    attempts = 0
    try:
        owner = f"framepack:project:{project.id}:scene:{scene.id}"
        with gpu_resource.exclusive_gpu(owner):
            for attempt in range(settings.framepack_max_retries + 1):
                attempts = attempt + 1
                raw_output.unlink(missing_ok=True)
                request = FramePackJobRequest(
                    job_id=f"{project.id}_{scene.scene_index:04d}_{_seed(project.id, scene.id)}_{attempt + 1}",
                    input_image=str(staged_input),
                    output_path=str(raw_output),
                    prompt=storyboard.motion_prompt,
                    seed=_seed(project.id, scene.id),
                    duration=duration,
                    width=settings.framepack_width,
                    height=settings.framepack_height,
                    fps=render_config.video.fps,
                    steps=settings.framepack_steps,
                    guidance_scale=settings.framepack_guidance_scale,
                )
                try:
                    result = client.render(request, project.id)
                    if not result.output_path or not raw_output.is_file():
                        raise FramePackError("FramePack Worker 未生成输出文件")
                    _normalize(raw_output, output_path, duration, project.id, render_config)
                    return {
                        "attempts": attempts,
                        "job_id": result.job_id,
                        "worker_output": result.output_path,
                    }
                except FramePackError as exc:
                    last_error = exc
        raise FramePackError(str(last_error or "FramePack 渲染失败"))
    finally:
        staged_input.unlink(missing_ok=True)
        raw_output.unlink(missing_ok=True)


def _normalize(
    raw_path: Path,
    output_path: Path,
    duration: float,
    project_id: str,
    config: ProjectRenderConfig,
) -> None:
    video = config.video
    run_ffmpeg(
        [
            "-y", "-i", str(raw_path),
            "-vf",
            (
                f"scale={video.width}:{video.height}:force_original_aspect_ratio=increase:"
                "in_range=auto:out_range=tv,"
                f"crop={video.width}:{video.height},fps={video.fps},"
                f"tpad=stop_mode=clone:stop_duration={duration:.3f},"
                f"trim=duration={duration:.3f},setpts=PTS-STARTPTS,"
                f"format={video.pixel_format},setparams=range=tv"
            ),
            "-t", f"{duration:.3f}", "-an", "-c:v", video.video_codec,
            "-preset", video.preset, "-crf", str(video.crf),
            "-pix_fmt", video.pixel_format, "-r", str(video.fps),
            "-movflags", "+faststart", str(output_path),
        ],
        project_id,
    )


def _storyboard(scene: VisualScene) -> StoryboardContent:
    if scene.storyboard_json:
        return StoryboardContent.model_validate_json(scene.storyboard_json)
    raise ValueError("FramePack 镜头缺少 Storyboard 运动描述")


def _seed(project_id: str, scene_id: str) -> int:
    digest = hashlib.sha256(f"{project_id}:{scene_id}:framepack".encode()).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF
