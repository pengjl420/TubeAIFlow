import json
import shutil
from pathlib import Path

from sqlmodel import Session, select

from app.config import get_settings
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
from app.services.rendering.scene_renderer import scene_output_path


def compose_final_video(session: Session, project: Project) -> dict:
    scenes = list(
        session.exec(
            select(VisualScene)
            .where(VisualScene.project_id == project.id)
            .order_by(VisualScene.scene_index)
        ).all()
    )
    if not scenes:
        raise ValueError("项目尚未生成视觉场景")
    scene_paths = [scene_output_path(project, scene) for scene in scenes]
    missing = [path.name for path in scene_paths if not path.is_file()]
    if missing:
        raise ValueError(f"仍有 {len(missing)} 个场景未完成渲染")
    audio_path = get_final_audio_path(project, get_settings().workspace_dir)
    if not audio_path.is_file():
        raise ValueError("完整配音文件不存在")

    base_dir = get_project_work_dir(project, get_settings().workspace_dir)
    ensure_project_dirs(base_dir)
    concat_path = base_dir / "renders" / "scenes.txt"
    concat_lines = [
        "file '" + path.as_posix().replace("'", "'\\''") + "'" for path in scene_paths
    ]
    concat_path.write_text(
        "\n".join(concat_lines),
        encoding="utf-8",
    )
    preview_path = base_dir / "renders" / "preview.mp4"
    output_path = get_final_video_path(project, get_settings().workspace_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audio_duration = probe_duration(audio_path)
    args = [
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        "-i",
        str(audio_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-t",
        f"{audio_duration:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-r",
        "30",
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
    run_ffmpeg(args, project.id)
    shutil.copyfile(output_path, preview_path)
    video_duration = probe_duration(output_path)
    report = {
        "path": str(output_path),
        "preview_path": str(preview_path),
        "subtitle_path": str(get_final_srt_path(project, get_settings().workspace_dir)),
        "scene_count": len(scenes),
        "audio_duration_seconds": audio_duration,
        "video_duration_seconds": video_duration,
    }
    report_path = base_dir / "reports" / "render_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
