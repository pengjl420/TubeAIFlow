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
from app.services.rendering.rough_cut_service import (
    PlannedTransition,
    build_transition_plan_for_durations,
)
from app.services.rendering.timeline_composer import scene_frame_window
from app.infrastructure.project_layout import load_project_config


def compose_visual_track(session: Session, project: Project) -> dict:
    settings = get_settings()
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

    base_dir = get_project_work_dir(project, settings.workspace_dir)
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
    project_config = load_project_config(project)
    transition_plan: list[PlannedTransition] = []
    if bool(project_config.get("storyboard_transition_enabled", True)):
        transition_plan = build_transition_plan_for_durations(
            [window[2] / config.video.fps for window in frame_windows],
            getattr(settings, "storyboard_transition_effects", []),
            group_min_clips=getattr(settings, "storyboard_transition_group_min_clips", 2),
            group_max_clips=getattr(settings, "storyboard_transition_group_max_clips", 5),
            min_per_group=getattr(settings, "storyboard_transition_min_per_group", 1),
            max_per_group=getattr(settings, "storyboard_transition_max_per_group", 2),
            duration=getattr(settings, "storyboard_transition_duration_seconds", 0.45),
        )
    if transition_plan:
        filter_script_path = base_dir / "renders" / "visual_track_filter.txt"
        transition_args = build_scene_transition_args(
            scene_paths,
            [window[2] / config.video.fps for window in frame_windows],
            transition_plan,
            output_path,
            config.video,
            expected_frame_count,
        )
        run_ffmpeg(
            _externalize_filter_graph(transition_args, filter_script_path),
            project.id,
        )
    else:
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
        "transitions": [item.__dict__ for item in transition_plan],
        "quality": quality,
    }
    report_path = base_dir / "reports" / "visual_track_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def build_scene_transition_args(
    scene_paths: list[Path],
    scene_durations: list[float],
    transition_plan: list[PlannedTransition],
    output_path: Path,
    video_config,
    expected_frame_count: int,
) -> list[str]:
    """Crossfade scene boundaries without shortening the narration timeline."""
    if len(scene_paths) != len(scene_durations) or len(scene_paths) < 2:
        raise ValueError("Scene transition inputs are invalid")
    transitions = {item.after_clip_index: item for item in transition_plan}
    if len(transitions) != len(transition_plan):
        raise ValueError("Only one transition effect can be assigned to a scene boundary")

    args = ["-y"]
    for path in scene_paths:
        args.extend(["-i", str(path)])
    filters = []
    for index in range(len(scene_paths)):
        transition = transitions.get(index + 1)
        padding = transition.duration if transition else 0.0
        suffix = f",tpad=stop_mode=clone:stop_duration={padding:.3f}" if padding else ""
        # xfade requires both inputs to use exactly the same time base. Scene
        # MP4s can still expose different container time bases even though they
        # share the same FPS and render settings, so normalize every input
        # before it reaches either xfade or concat.
        filters.append(
            f"[{index}:v]settb=AVTB,setpts=PTS-STARTPTS{suffix}[v{index}]"
        )

    current_label = "v0"
    current_duration = scene_durations[0]
    for index in range(1, len(scene_paths)):
        transition = transitions.get(index)
        output_label = f"join{index}"
        if transition:
            filters.append(
                f"[{current_label}][v{index}]xfade=transition={transition.effect}:"
                f"duration={transition.duration:.3f}:offset={current_duration:.3f}[{output_label}]"
            )
        else:
            filters.append(
                f"[{current_label}][v{index}]concat=n=2:v=1:a=0[{output_label}]"
            )
        current_label = output_label
        current_duration += scene_durations[index]

    args.extend([
        "-filter_complex", ";".join(filters),
        "-map", f"[{current_label}]",
        "-frames:v", str(expected_frame_count),
        "-an",
        "-c:v", video_config.video_codec,
        "-preset", video_config.preset,
        "-crf", str(video_config.crf),
        "-pix_fmt", video_config.pixel_format,
        "-r", str(video_config.fps),
        "-movflags", "+faststart",
        str(output_path),
    ])
    return args


def _externalize_filter_graph(args: list[str], script_path: Path) -> list[str]:
    """Keep large scene graphs out of the Windows process command line."""
    try:
        filter_index = args.index("-filter_complex")
        filter_graph = args[filter_index + 1]
    except (ValueError, IndexError) as exc:
        raise ValueError("Transition command is missing its filter graph") from exc
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(filter_graph, encoding="utf-8")
    return [
        *args[:filter_index],
        "-filter_complex_script",
        str(script_path),
        *args[filter_index + 2 :],
    ]
