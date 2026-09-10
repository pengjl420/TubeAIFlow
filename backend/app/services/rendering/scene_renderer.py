import hashlib
import json
from pathlib import Path

from sqlmodel import Session, select

from app.config import get_settings
from app.infrastructure.atomic_files import atomic_output_path
from app.infrastructure.artifacts import sha256_file
from app.infrastructure.ffmpeg import run_ffmpeg
from app.infrastructure.project_layout import ensure_project_dirs, get_project_work_dir
from app.models.media import (
    LIBRARY_ROLE_LOCAL_LANDSCAPE,
    LIBRARY_ROLE_LOCAL_SEMANTIC,
    LIBRARY_ROLE_PROJECT_GENERATED,
    SELECTION_STAGE_GENERATED_IMAGE,
    SELECTION_STAGE_LOCAL_LANDSCAPE_MIX,
    SELECTION_STAGE_MANUAL_LOCAL_ASSET,
    MediaFile,
    MediaShot,
    SceneAssignment,
)
from app.models.project import Project
from app.models.storyboard import VisualScene
from app.services.rendering import timeline_composer
from app.services.rendering.motion_presets import select_motion_preset
from app.services.rendering.render_config import get_project_render_config
from app.services.rendering.ffmpeg_runner import run_with_encoder_fallback
from app.services.rendering.scene_quality_checker import check_scene_video


RENDER_TIMING_VERSION = 4


def render_all_scenes(session: Session, project: Project) -> dict:
    scenes = list(
        session.exec(
            select(VisualScene)
            .where(VisualScene.project_id == project.id)
            .order_by(VisualScene.scene_index)
        ).all()
    )
    if not scenes:
        raise ValueError("项目尚未生成视觉场景")
    assignments: dict[str, list[SceneAssignment]] = {}
    for item in session.exec(
        select(SceneAssignment).where(SceneAssignment.project_id == project.id)
    ).all():
        assignments.setdefault(item.scene_id, []).append(item)
    for scene_items in assignments.values():
        scene_items.sort(key=lambda item: (item.sequence_index, item.created_at))
    missing = []
    for scene in scenes:
        scene_items = assignments.get(scene.id, [])
        _, covered_ms = timeline_composer.reflow_scene_assignments(session, scene, scene_items)
        if not scene_items or covered_ms < scene.end_ms - scene.start_ms:
            missing.append(scene.scene_index)
    if missing:
        raise ValueError(f"仍有 {len(missing)} 个场景未确认素材")

    rendered = []
    skipped = []
    for scene in scenes:
        result = render_scene(
            session,
            project,
            scene,
            assignments[scene.id],
        )
        (skipped if result["skipped"] else rendered).append(result)
    return {"rendered": rendered, "skipped": skipped, "total": len(scenes)}


def render_scene(
    session: Session,
    project: Project,
    scene: VisualScene,
    assignment: SceneAssignment | list[SceneAssignment] | None = None,
) -> dict:
    if scene.project_id != project.id:
        raise ValueError("视觉场景不属于当前项目")
    if assignment is None:
        assignments = timeline_composer.scene_assignments(session, scene.id)
    elif isinstance(assignment, list):
        assignments = assignment
    else:
        assignments = [assignment]
    if not assignments:
        raise ValueError("场景尚未分配生成图片")

    settings = get_settings()
    base_dir = get_project_work_dir(project, settings.workspace_dir)
    ensure_project_dirs(base_dir)
    output_path = base_dir / "renders" / "scenes" / f"scene_{scene.scene_index:04d}.mp4"
    manifest_path = base_dir / "renders" / "scenes" / "manifest.json"
    assignments, covered_ms = timeline_composer.reflow_scene_assignments(
        session, scene, assignments
    )
    if covered_ms < scene.end_ms - scene.start_ms:
        raise ValueError(
            f"场景 {scene.scene_index} 的镜头轨道尚缺 "
            f"{(scene.end_ms - scene.start_ms - covered_ms) / 1000:.2f} 秒"
        )
    clips = []
    for item in assignments:
        shot = session.get(MediaShot, item.media_shot_id)
        media_file = session.get(MediaFile, shot.media_file_id) if shot else None
        if not shot or not media_file:
            raise ValueError("场景指派的素材镜头不存在")
        validate_visual_assignment(item, shot, media_file)
        source_path = Path(media_file.path).resolve()
        if not source_path.is_file():
            raise ValueError(f"素材文件不存在：{source_path}")
        clips.append((item, shot, media_file, source_path))

    config = get_project_render_config(project)
    start_frame, end_frame, frame_count = timeline_composer.scene_frame_window(
        scene, config.video.fps
    )
    duration = frame_count / config.video.fps
    presets = _resolved_presets(project, scene, clips)
    signature = _render_signature(
        scene,
        clips,
        config.model_dump(),
        presets,
    )
    manifest = _read_json(manifest_path)
    previous = manifest.get(scene.id)
    if (
        previous
        and previous.get("signature") == signature
        and output_path.is_file()
        and previous.get("artifact_hash") == sha256_file(output_path)
    ):
        try:
            quality = check_scene_video(
                output_path,
                duration,
                config,
                expected_frame_count=frame_count,
            )
            return _result(
                scene,
                output_path,
                signature,
                True,
                presets,
                quality,
                "ffmpeg",
                "ffmpeg",
                None,
                previous.get("attempts", 1),
            )
        except RuntimeError:
            pass

    attempts = 1
    with atomic_output_path(output_path) as temporary_output:
        args = _scene_ffmpeg_args(
            temporary_output,
            frame_count,
            scene.start_ms,
            clips,
            presets,
            config.video,
        )
        run_with_encoder_fallback(args, project.id, run_ffmpeg)
        quality = check_scene_video(
            temporary_output,
            duration,
            config,
            expected_frame_count=frame_count,
        )
    actual_duration = quality["metadata"]["duration_ms"] / 1000
    artifact_hash = sha256_file(output_path)
    manifest[scene.id] = {
        "scene_index": scene.scene_index,
        "render_timing_version": RENDER_TIMING_VERSION,
        "signature": signature,
        "artifact_hash": artifact_hash,
        "path": str(output_path),
        "duration_seconds": actual_duration,
        "timeline_duration_seconds": (scene.end_ms - scene.start_ms) / 1000,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "frame_count": frame_count,
        "requested_provider": "ffmpeg",
        "provider": "ffmpeg",
        "route_reason": "FFmpeg 是默认渲染方式",
        "attempts": attempts,
        "fallback_reason": None,
        "motion_presets": presets,
        "quality": quality,
    }
    _write_json(manifest_path, manifest)
    scene.status = "rendered"
    session.add(scene)
    session.commit()
    return _result(
        scene,
        output_path,
        signature,
        False,
        presets,
        quality,
        "ffmpeg",
        "ffmpeg",
        None,
        attempts,
    )


def validate_visual_assignment(
    assignment: SceneAssignment,
    shot: MediaShot,
    media_file: MediaFile,
) -> None:
    if assignment.selection_stage == SELECTION_STAGE_LOCAL_LANDSCAPE_MIX:
        if (
            shot.library_role != LIBRARY_ROLE_LOCAL_LANDSCAPE
            or media_file.library_role != LIBRARY_ROLE_LOCAL_LANDSCAPE
            or media_file.media_type != "video"
        ):
            raise ValueError("Mixed-mode landscape assignment is not a registered local video")
        return
    if assignment.selection_stage == SELECTION_STAGE_MANUAL_LOCAL_ASSET:
        if (
            shot.library_role != LIBRARY_ROLE_LOCAL_SEMANTIC
            or media_file.library_role != LIBRARY_ROLE_LOCAL_SEMANTIC
            or media_file.media_type not in {"image", "video"}
        ):
            raise ValueError("手动选择的本地素材不是已注册的图片或视频")
        return
    if assignment.selection_stage != SELECTION_STAGE_GENERATED_IMAGE:
        raise ValueError(f"不支持的画面来源：{assignment.selection_stage}")
    if (
        shot.library_role != LIBRARY_ROLE_PROJECT_GENERATED
        or media_file.library_role != LIBRARY_ROLE_PROJECT_GENERATED
    ):
        raise ValueError("场景画面不是当前项目生成的图片")


def scene_output_path(project: Project, scene: VisualScene) -> Path:
    return (
        get_project_work_dir(project, get_settings().workspace_dir)
        / "renders"
        / "scenes"
        / f"scene_{scene.scene_index:04d}.mp4"
    )


def scene_renders_need_timing_refresh(
    project: Project,
    scenes: list[VisualScene],
    config,
) -> bool:
    """Detect manifests created before absolute frame timing was introduced."""
    base_dir = get_project_work_dir(project, get_settings().workspace_dir)
    manifest_path = base_dir / "renders" / "scenes" / "manifest.json"
    if not manifest_path.is_file():
        return False
    manifest = _read_json(manifest_path)
    for scene in scenes:
        start_frame, end_frame, frame_count = timeline_composer.scene_frame_window(
            scene, config.video.fps
        )
        entry = manifest.get(scene.id)
        if not entry or (
            entry.get("render_timing_version") != RENDER_TIMING_VERSION
            or entry.get("start_frame") != start_frame
            or entry.get("end_frame") != end_frame
            or entry.get("frame_count") != frame_count
        ):
            return True
    return False


def _scene_ffmpeg_args(
    output_path: Path,
    frame_count: int,
    scene_start_ms: int,
    clips: list[tuple[SceneAssignment, MediaShot, MediaFile, Path]],
    presets: list[str],
    video_config,
) -> list[str]:
    args = ["-y"]
    filters = []
    labels = []
    allocated_frame_count = 0
    for index, (assignment, shot, media_file, source_path) in enumerate(clips):
        if media_file.media_type == "image":
            args.extend(["-loop", "1", "-i", str(source_path)])
        else:
            source_start = (shot.start_ms + assignment.trim_start_ms) / 1000
            source_duration = (
                (assignment.scene_offset_end_ms - assignment.scene_offset_start_ms)
                * assignment.playback_speed
                / 1000
            )
            args.extend(
                [
                    "-ss",
                    f"{source_start:.3f}",
                    "-t",
                    f"{source_duration:.3f}",
                    "-i",
                    str(source_path),
                ]
            )
        placement_duration = (
            assignment.scene_offset_end_ms - assignment.scene_offset_start_ms
        ) / 1000
        clip_start_frame = timeline_composer.timeline_frame(
            scene_start_ms + assignment.scene_offset_start_ms,
            video_config.fps,
        )
        clip_end_frame = timeline_composer.timeline_frame(
            scene_start_ms + assignment.scene_offset_end_ms,
            video_config.fps,
        )
        clip_frame_count = clip_end_frame - clip_start_frame
        if clip_frame_count <= 0:
            raise ValueError(f"镜头 {assignment.sequence_index} 的显示时长不足一帧")
        allocated_frame_count += clip_frame_count
        label = f"v{index}"
        filters.append(
            _visual_filter(
                index,
                media_file,
                placement_duration,
                assignment.playback_speed,
                label,
                assignment,
                presets[index],
                video_config,
                target_frame_count=clip_frame_count,
            )
        )
        labels.append(f"[{label}]")
    if allocated_frame_count != frame_count:
        raise RuntimeError(
            f"镜头帧数之和 {allocated_frame_count} 与场景目标帧数 {frame_count} 不一致"
        )
    if len(labels) == 1:
        filters.append(f"{labels[0]}null[v]")
    else:
        filters.append(f"{''.join(labels)}concat=n={len(labels)}:v=1:a=0[v]")
    filter_graph = ";".join(filters)
    args.extend(
        [
            "-filter_complex",
            filter_graph,
            "-map",
            "[v]",
            "-frames:v",
            str(frame_count),
            "-an",
            "-c:v",
            video_config.video_codec,
            "-preset",
            video_config.preset,
            "-crf",
            str(video_config.crf),
            "-pix_fmt",
            video_config.pixel_format,
            "-r",
            str(video_config.fps),
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    return args


def _visual_filter(
    input_index: int,
    media_file: MediaFile,
    duration: float,
    speed: float,
    output_label: str,
    assignment: SceneAssignment,
    preset: str,
    video_config,
    *,
    target_frame_count: int | None = None,
) -> str:
    target_width = video_config.width
    target_height = video_config.height
    target_fps = video_config.fps
    timing = f"setpts=(PTS-STARTPTS)/{speed:.6f}"
    if media_file.media_type == "image":
        frames = target_frame_count or max(1, round(duration * target_fps))
        start_zoom = min(assignment.zoom_start, assignment.zoom_end)
        end_zoom = max(assignment.zoom_start, assignment.zoom_end)
        if preset in {
            "pan_left_to_right",
            "pan_right_to_left",
            "pan_top_to_bottom",
            "pan_bottom_to_top",
            "diagonal_top_left",
            "diagonal_top_right",
        }:
            start_zoom = max(start_zoom, 1.06)
            end_zoom = max(end_zoom, start_zoom)
        delta = max(0.000001, (end_zoom - start_zoom) / frames)
        if preset in {"slow_zoom_out", "environment_pull_out"}:
            zoom = f"if(eq(on,0),{end_zoom:.6f},max(zoom-{delta:.8f},{start_zoom:.6f}))"
        elif preset == "static":
            zoom = f"{start_zoom:.6f}"
        elif preset == "subtle_breathing":
            center = max(1.015, min(1.035, (start_zoom + end_zoom) / 2))
            amplitude = min(0.01, max(0.003, (end_zoom - start_zoom) / 2))
            zoom = f"{center:.6f}+{amplitude:.6f}*sin(2*PI*on/{frames})"
        else:
            zoom = f"if(eq(on,0),{start_zoom:.6f},min(zoom+{delta:.8f},{end_zoom:.6f}))"
        if preset == "pan_left_to_right" or assignment.pan_direction == "right":
            x = f"(iw-iw/zoom)*on/{frames}"
        elif preset == "pan_right_to_left" or assignment.pan_direction == "left":
            x = f"(iw-iw/zoom)*(1-on/{frames})"
        elif preset == "diagonal_top_left":
            x = f"(iw-iw/zoom)*(1-on/{frames})"
        elif preset == "diagonal_top_right":
            x = f"(iw-iw/zoom)*on/{frames}"
        elif assignment.crop_anchor == "left":
            x = "0"
        elif assignment.crop_anchor == "right":
            x = "iw-iw/zoom"
        else:
            x = "iw/2-(iw/zoom/2)"
        if (
            preset in {"pan_top_to_bottom", "diagonal_top_right"}
            or assignment.pan_direction == "down"
        ):
            y = f"(ih-ih/zoom)*on/{frames}"
        elif (
            preset in {"pan_bottom_to_top", "diagonal_top_left"} or assignment.pan_direction == "up"
        ):
            y = f"(ih-ih/zoom)*(1-on/{frames})"
        elif assignment.crop_anchor == "top":
            y = "0"
        elif assignment.crop_anchor == "bottom":
            y = "ih-ih/zoom"
        else:
            y = "ih/2-(ih/zoom/2)"
        motion_filter = (
            f"zoompan=z='{zoom}':x='{x}':y='{y}':d=1:"
            f"s={target_width}x{target_height}:fps={target_fps},"
            f"trim=end_frame={frames},setpts=PTS-STARTPTS,"
            f"format={video_config.pixel_format},setsar=1,"
            f"setparams=range=tv[{output_label}]"
        )
        if media_file.width and media_file.height and media_file.width / media_file.height < 1.2:
            return (
                f"[{input_index}:v]split=2[bg{input_index}][fg{input_index}];"
                f"[bg{input_index}]scale={target_width}:{target_height}:force_original_aspect_ratio=increase:in_range=auto:out_range=tv,"
                f"crop={target_width}:{target_height},boxblur=20:10[blur{input_index}];"
                f"[fg{input_index}]scale={target_width}:{target_height}:force_original_aspect_ratio=decrease:in_range=auto:out_range=tv[front{input_index}];"
                f"[blur{input_index}][front{input_index}]overlay=(W-w)/2:(H-h)/2[base{input_index}];"
                f"[base{input_index}]{motion_filter}"
            )
        return (
            f"[{input_index}:v]scale={target_width}:{target_height}:"
            f"force_original_aspect_ratio=increase:in_range=auto:out_range=tv,"
            f"crop={target_width}:{target_height},"
            f"{motion_filter}"
        )
    frames = target_frame_count or max(1, round(duration * target_fps))
    finish = (
        f"fps={target_fps},tpad=stop_mode=clone:stop_duration=0.250,"
        f"trim=end_frame={frames},setpts=PTS-STARTPTS,"
        f"format={video_config.pixel_format},setsar=1,"
        f"setparams=range=tv[{output_label}]"
    )
    if media_file.width and media_file.height and media_file.width / media_file.height < 1.2:
        return (
            f"[{input_index}:v]{timing},split=2[bg{input_index}][fg{input_index}];"
            f"[bg{input_index}]scale={target_width}:{target_height}:force_original_aspect_ratio=increase:in_range=auto:out_range=tv,"
            f"crop={target_width}:{target_height},boxblur=20:10[blur{input_index}];"
            f"[fg{input_index}]scale={target_width}:{target_height}:force_original_aspect_ratio=decrease:in_range=auto:out_range=tv[front{input_index}];"
            f"[blur{input_index}][front{input_index}]overlay=(W-w)/2:(H-h)/2,{finish}"
        )
    return (
        f"[{input_index}:v]{timing},scale={target_width}:{target_height}:"
        f"force_original_aspect_ratio=increase:in_range=auto:out_range=tv,"
        f"crop={target_width}:{target_height},{finish}"
    )


def _render_signature(
    scene: VisualScene,
    clips: list[tuple[SceneAssignment, MediaShot, MediaFile, Path]],
    render_config: dict,
    presets: list[str],
) -> str:
    value = {
        "render_timing_version": RENDER_TIMING_VERSION,
        "scene": [scene.id, scene.start_ms, scene.end_ms],
        "clips": [
            {
                "assignment": assignment.model_dump(),
                "shot": [shot.id, shot.start_ms, shot.end_ms],
                "media": [media_file.id, media_file.path, source_path.stat().st_mtime_ns],
            }
            for assignment, shot, media_file, source_path in clips
        ],
        "render_config": render_config,
        "motion_presets": presets,
    }
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _result(
    scene: VisualScene,
    path: Path,
    signature: str,
    skipped: bool,
    presets: list[str],
    quality: dict,
    requested_provider: str,
    provider: str,
    fallback_reason: str | None,
    attempts: int,
) -> dict:
    return {
        "scene_id": scene.id,
        "scene_index": scene.scene_index,
        "path": str(path),
        "signature": signature,
        "skipped": skipped,
        "requested_provider": requested_provider,
        "provider": provider,
        "fallback_reason": fallback_reason,
        "attempts": attempts,
        "motion_presets": presets,
        "quality": quality,
    }


def _resolved_presets(
    project: Project,
    scene: VisualScene,
    clips: list[tuple[SceneAssignment, MediaShot, MediaFile, Path]],
) -> list[str]:
    presets: list[str] = []
    for assignment, _shot, media_file, _source_path in clips:
        if media_file.media_type != "image":
            presets.append("source_video")
            continue
        presets.append(select_motion_preset(project.id, scene, assignment, presets))
    return presets


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
