import hashlib
import json
from pathlib import Path

from sqlmodel import Session, select

from app.config import get_settings
from app.infrastructure.ffmpeg import probe_duration, run_ffmpeg
from app.infrastructure.project_layout import ensure_project_dirs, get_project_work_dir
from app.models.media import (
    LIBRARY_ROLE_LANDSCAPE_FALLBACK,
    LIBRARY_ROLE_SEMANTIC,
    LIBRARY_ROLE_THEMED_FALLBACK,
    MediaFile,
    MediaShot,
    SceneAssignment,
)
from app.models.project import Project
from app.models.storyboard import VisualScene
from app.services.rendering import timeline_composer


TARGET_WIDTH = 1920
TARGET_HEIGHT = 1080
TARGET_FPS = 30


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
        result = render_scene(session, project, scene, assignments[scene.id])
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
    if not assignments or any(not item.manual_confirmed for item in assignments):
        raise ValueError("请先在素材审核中确认该场景使用的镜头")

    duration = (scene.end_ms - scene.start_ms) / 1000
    if duration <= 0:
        raise ValueError("场景时长必须大于零")
    base_dir = get_project_work_dir(project, get_settings().workspace_dir)
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
        validate_semantic_assignment(item, shot, media_file)
        source_path = Path(media_file.path).resolve()
        if not source_path.is_file():
            raise ValueError(f"素材文件不存在：{source_path}")
        clips.append((item, shot, media_file, source_path))

    signature = _render_signature(scene, clips)
    manifest = _read_json(manifest_path)
    previous = manifest.get(scene.id)
    if previous and previous.get("signature") == signature and output_path.is_file():
        try:
            if abs(probe_duration(output_path) - duration) <= 0.12:
                return _result(scene, output_path, signature, True)
        except RuntimeError:
            pass

    args = _scene_ffmpeg_args(output_path, duration, clips)
    run_ffmpeg(args, project.id)
    actual_duration = probe_duration(output_path)
    if abs(actual_duration - duration) > 0.12:
        raise RuntimeError(
            f"场景 {scene.scene_index} 渲染时长不匹配："
            f"expected={duration:.3f}s actual={actual_duration:.3f}s"
        )
    manifest[scene.id] = {
        "scene_index": scene.scene_index,
        "signature": signature,
        "path": str(output_path),
        "duration_seconds": actual_duration,
    }
    _write_json(manifest_path, manifest)
    scene.status = "rendered"
    session.add(scene)
    session.commit()
    return _result(scene, output_path, signature, False)


def validate_semantic_assignment(
    assignment: SceneAssignment,
    shot: MediaShot,
    media_file: MediaFile,
) -> None:
    expected_role = {
        "local_semantic": LIBRARY_ROLE_SEMANTIC,
        "remote_semantic": LIBRARY_ROLE_SEMANTIC,
        "manual_upload": LIBRARY_ROLE_SEMANTIC,
        LIBRARY_ROLE_THEMED_FALLBACK: LIBRARY_ROLE_THEMED_FALLBACK,
        LIBRARY_ROLE_LANDSCAPE_FALLBACK: LIBRARY_ROLE_LANDSCAPE_FALLBACK,
        "manual": shot.library_role,
    }.get(assignment.selection_stage)
    if expected_role is None:
        raise ValueError(f"未知的素材选择阶段：{assignment.selection_stage}")
    if shot.library_role != expected_role or media_file.library_role != expected_role:
        raise ValueError("场景素材角色与选择阶段不匹配，已拒绝渲染")
    if media_file.review_status != "approved" or not media_file.enabled:
        raise ValueError("场景素材未审核通过或已停用")


def scene_output_path(project: Project, scene: VisualScene) -> Path:
    return (
        get_project_work_dir(project, get_settings().workspace_dir)
        / "renders"
        / "scenes"
        / f"scene_{scene.scene_index:04d}.mp4"
    )


def _scene_ffmpeg_args(
    output_path: Path,
    duration: float,
    clips: list[tuple[SceneAssignment, MediaShot, MediaFile, Path]],
) -> list[str]:
    args = ["-y"]
    filters = []
    labels = []
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
                ["-ss", f"{source_start:.3f}", "-t", f"{source_duration:.3f}", "-i", str(source_path)]
            )
        placement_duration = (
            assignment.scene_offset_end_ms - assignment.scene_offset_start_ms
        ) / 1000
        label = f"v{index}"
        filters.append(
            _visual_filter(index, media_file, placement_duration, assignment.playback_speed, label)
        )
        labels.append(f"[{label}]")
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
            "-t",
            f"{duration:.3f}",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(TARGET_FPS),
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
) -> str:
    timing = f"setpts=(PTS-STARTPTS)/{speed:.6f}"
    if media_file.media_type == "image" and (
        not media_file.width or not media_file.height or media_file.width / media_file.height >= 1.2
    ):
        return (
            f"[{input_index}:v]scale={TARGET_WIDTH}:{TARGET_HEIGHT}:"
            f"force_original_aspect_ratio=increase,crop={TARGET_WIDTH}:{TARGET_HEIGHT},"
            f"zoompan=z='min(zoom+0.0003,1.06)':x='iw/2-(iw/zoom/2)':"
            f"y='ih/2-(ih/zoom/2)':d=1:s={TARGET_WIDTH}x{TARGET_HEIGHT}:fps={TARGET_FPS},"
            f"trim=duration={duration:.3f},setpts=PTS-STARTPTS,format=yuv420p[{output_label}]"
        )
    finish = (
        f"fps={TARGET_FPS},tpad=stop_mode=clone:stop_duration=0.250,"
        f"trim=duration={duration:.3f},setpts=PTS-STARTPTS,format=yuv420p[{output_label}]"
    )
    if media_file.width and media_file.height and media_file.width / media_file.height < 1.2:
        return (
            f"[{input_index}:v]{timing},split=2[bg{input_index}][fg{input_index}];"
            f"[bg{input_index}]scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={TARGET_WIDTH}:{TARGET_HEIGHT},boxblur=20:10[blur{input_index}];"
            f"[fg{input_index}]scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=decrease[front{input_index}];"
            f"[blur{input_index}][front{input_index}]overlay=(W-w)/2:(H-h)/2,{finish}"
        )
    return (
        f"[{input_index}:v]{timing},scale={TARGET_WIDTH}:{TARGET_HEIGHT}:"
        f"force_original_aspect_ratio=increase,crop={TARGET_WIDTH}:{TARGET_HEIGHT},{finish}"
    )


def _render_signature(
    scene: VisualScene,
    clips: list[tuple[SceneAssignment, MediaShot, MediaFile, Path]],
) -> str:
    value = {
        "scene": [scene.id, scene.start_ms, scene.end_ms],
        "clips": [
            {
                "assignment": assignment.model_dump(),
                "shot": [shot.id, shot.start_ms, shot.end_ms],
                "media": [media_file.id, media_file.path, source_path.stat().st_mtime_ns],
            }
            for assignment, shot, media_file, source_path in clips
        ],
        "target": [TARGET_WIDTH, TARGET_HEIGHT, TARGET_FPS],
    }
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _result(scene: VisualScene, path: Path, signature: str, skipped: bool) -> dict:
    return {
        "scene_id": scene.id,
        "scene_index": scene.scene_index,
        "path": str(path),
        "signature": signature,
        "skipped": skipped,
    }


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
