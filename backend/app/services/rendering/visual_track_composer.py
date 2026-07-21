import json
from pathlib import Path

from sqlmodel import Session, select

from app.config import get_settings
from app.infrastructure.ffmpeg import run_ffmpeg
from app.infrastructure.project_layout import ensure_project_dirs, get_project_work_dir
from app.models.project import Project
from app.models.storyboard import VisualScene
from app.services.rendering.render_config import get_project_render_config
from app.services.rendering.scene_quality_checker import check_scene_video
from app.services.rendering import scene_renderer
from app.services.rendering.timeline_composer import scene_frame_window


def compose_visual_track(session: Session, project: Project) -> dict:
    scenes = list(
        session.exec(
            select(VisualScene)
            .where(VisualScene.project_id == project.id)
            .order_by(VisualScene.scene_index)
        ).all()
    )
    if not scenes:
        raise ValueError("项目尚未生成视觉场景")
    scene_paths = [scene_renderer.scene_output_path(project, scene) for scene in scenes]
    missing = [path.name for path in scene_paths if not path.is_file()]
    if missing:
        raise ValueError(f"仍有 {len(missing)} 个场景未完成渲染")

    base_dir = get_project_work_dir(project, get_settings().workspace_dir)
    ensure_project_dirs(base_dir)
    concat_path = base_dir / "renders" / "visual_track_scenes.txt"
    concat_path.write_text(
        "\n".join("file '" + path.as_posix().replace("'", "'\\''") + "'" for path in scene_paths),
        encoding="utf-8",
    )
    output_path = base_dir / "renders" / "visual_track.mp4"
    config = get_project_render_config(project)
    if scene_renderer.scene_renders_need_timing_refresh(project, scenes, config):
        scene_renderer.render_all_scenes(session, project)
    frame_windows = [scene_frame_window(scene, config.video.fps) for scene in scenes]
    expected_frame_count = sum(window[2] for window in frame_windows)
    expected_duration = expected_frame_count / config.video.fps
    timeline_duration = sum((scene.end_ms - scene.start_ms) / 1000 for scene in scenes)
    run_ffmpeg(
        [
            "-y", "-f", "concat", "-safe", "0", "-i", str(concat_path),
            "-map", "0:v:0", "-an", "-c:v", "copy", "-movflags", "+faststart",
            str(output_path),
        ],
        project.id,
    )
    quality = check_scene_video(
        output_path,
        expected_duration,
        config,
        expected_frame_count=expected_frame_count,
    )
    report = {
        "path": str(output_path),
        "scene_count": len(scenes),
        "duration_seconds": expected_duration,
        "timeline_duration_seconds": timeline_duration,
        "expected_frame_count": expected_frame_count,
        "quality": quality,
    }
    report_path = base_dir / "reports" / "visual_track_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
