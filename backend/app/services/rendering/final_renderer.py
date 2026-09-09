import shutil

from sqlmodel import Session, select

from app.config import get_settings
from app.infrastructure.atomic_files import write_json_atomic
from app.infrastructure.ffmpeg import probe_duration, run_ffmpeg
from app.infrastructure.project_layout import (
    ensure_project_dirs,
    get_final_audio_path,
    get_final_srt_path,
    get_final_video_path,
    get_project_work_dir,
)
from app.models.project import Project
from app.models.storyboard import VisualScene
from app.services.rendering.render_config import get_project_render_config


def compose_final_video(session: Session, project: Project) -> dict:
    scene_count = len(
        list(session.exec(select(VisualScene.id).where(VisualScene.project_id == project.id)).all())
    )
    if not scene_count:
        raise ValueError("项目尚未生成视觉场景")
    audio_path = get_final_audio_path(project, get_settings().workspace_dir)
    if not audio_path.is_file():
        raise ValueError("完整配音文件不存在")

    base_dir = get_project_work_dir(project, get_settings().workspace_dir)
    ensure_project_dirs(base_dir)
    visual_track_path = base_dir / "renders" / "visual_track.mp4"
    if not visual_track_path.is_file():
        raise ValueError("纯视频轨道尚未生成")
    preview_path = base_dir / "renders" / "preview.mp4"
    output_path = get_final_video_path(project, get_settings().workspace_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audio_duration = probe_duration(audio_path)
    render_config = get_project_render_config(project).video
    subtitle_path = get_final_srt_path(project, get_settings().workspace_dir)
    args = [
        "-y",
        "-i",
        str(visual_track_path),
        "-i",
        str(audio_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-t",
        f"{audio_duration:.3f}",
    ]
    if subtitle_path.is_file():
        args.extend(["-vf", subtitle_filter(subtitle_path)])
    args.extend(
        [
            "-c:v",
            render_config.video_codec,
            "-preset",
            render_config.preset,
            "-crf",
            str(render_config.crf),
            "-pix_fmt",
            render_config.pixel_format,
            "-r",
            str(render_config.fps),
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    run_ffmpeg(args, project.id)
    shutil.copyfile(output_path, preview_path)
    video_duration = probe_duration(output_path)
    report = {
        "path": str(output_path),
        "preview_path": str(preview_path),
        "visual_track_path": str(visual_track_path),
        "scene_count": scene_count,
        "audio_duration_seconds": audio_duration,
        "video_duration_seconds": video_duration,
        "subtitles_burned": subtitle_path.is_file(),
    }
    write_json_atomic(base_dir / "reports" / "render_report.json", report)
    return report


def subtitle_filter(path) -> str:
    """Return an FFmpeg subtitles filter safe for Windows drive-letter paths."""
    normalized = str(path.resolve()).replace("\\", "/")
    normalized = normalized.replace(":", r"\:").replace("'", r"\'")
    return f"subtitles=filename='{normalized}'"
