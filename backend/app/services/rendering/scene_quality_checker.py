from pathlib import Path

from app.infrastructure.ffmpeg import probe_media
from app.schemas.render import ProjectRenderConfig


def check_scene_video(
    video_path: Path,
    expected_duration: float,
    config: ProjectRenderConfig,
) -> dict:
    if not video_path.is_file() or video_path.stat().st_size <= 0:
        raise RuntimeError(f"场景视频不存在或为空：{video_path}")
    metadata = probe_media(video_path)
    issues: list[str] = []
    video = config.video
    tolerance = config.policy.duration_tolerance_frames / video.fps
    actual_duration = (metadata.get("duration_ms") or 0) / 1000
    if metadata.get("video_stream_count") != 1:
        issues.append("必须且只能包含一个视频流")
    if config.policy.verify_no_audio and metadata.get("audio_stream_count") != 0:
        issues.append("检测到意外音频流")
    if metadata.get("width") != video.width or metadata.get("height") != video.height:
        issues.append(f"分辨率不是 {video.width}x{video.height}")
    if metadata.get("codec_name") != _expected_codec_name(video.video_codec):
        issues.append(f"视频编码不是 {_expected_codec_name(video.video_codec)}")
    if metadata.get("pixel_format") != video.pixel_format:
        issues.append(f"像素格式不是 {video.pixel_format}")
    if abs(actual_duration - expected_duration) > tolerance + 0.002:
        issues.append(
            f"时长误差 {abs(actual_duration - expected_duration):.3f}s 超过 {tolerance:.3f}s"
        )
    frame_rate = metadata.get("frame_rate_value")
    if frame_rate is None or abs(frame_rate - video.fps) > 0.01:
        issues.append(f"帧率不是 {video.fps} FPS")
    result = {
        "passed": not issues,
        "path": str(video_path),
        "expected_duration_seconds": expected_duration,
        "metadata": metadata,
        "issues": issues,
    }
    if issues:
        raise RuntimeError("场景视频规格检查失败：" + "；".join(issues))
    return result


def _expected_codec_name(codec: str) -> str:
    return "h264" if codec in {"libx264", "h264"} else codec

