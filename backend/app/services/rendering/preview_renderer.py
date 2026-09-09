from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sqlmodel import Session, select

from app.config import get_settings
from app.infrastructure.atomic_files import write_json_atomic, write_text_atomic
from app.infrastructure.ffmpeg import probe_duration, run_ffmpeg
from app.infrastructure.project_layout import (
    ensure_project_dirs,
    get_final_audio_path,
    get_project_work_dir,
)
from app.models.project import Project
from app.models.storyboard import SubtitleCue, VisualScene
from app.services.rendering import final_renderer, scene_renderer
from app.shared.time import seconds_to_srt_time


def render_timeline_preview(
    session: Session,
    project: Project,
    *,
    start_ms: int,
    duration_ms: int,
) -> dict:
    if start_ms < 0:
        raise ValueError("Preview start must not be negative")
    if duration_ms not in {30_000, 60_000}:
        raise ValueError("Preview duration must be 30 or 60 seconds")

    settings = get_settings()
    base_dir = get_project_work_dir(project, settings.workspace_dir)
    ensure_project_dirs(base_dir)
    preview_dir = base_dir / "renders" / "preview"
    audio_path = get_final_audio_path(project, settings.workspace_dir)
    if not audio_path.is_file():
        raise ValueError("完整配音文件不存在")
    audio_duration_ms = round(probe_duration(audio_path) * 1000)
    if start_ms >= audio_duration_ms:
        raise ValueError("Preview start is outside the project duration")
    actual_duration_ms = min(duration_ms, audio_duration_ms - start_ms)
    visual_path, visual_seek_ms, concat_input, visual_sources = _preview_visual_source(
        session, project, base_dir, preview_dir, start_ms, actual_duration_ms
    )
    cues = _preview_cues(session, project.id, start_ms, actual_duration_ms)
    signature = _preview_signature(visual_sources, audio_path, start_ms, actual_duration_ms, cues)
    output_path = preview_dir / f"range_{start_ms}_{actual_duration_ms}_{signature[:12]}.mp4"
    manifest_path = preview_dir / "manifest.json"
    if output_path.is_file():
        return _result(output_path, start_ms, actual_duration_ms, signature, skipped=True)

    subtitle_path = _write_preview_subtitles(
        cues, preview_dir, start_ms, actual_duration_ms, signature
    )
    args = build_preview_args(
        visual_path,
        audio_path,
        output_path,
        visual_seek_ms=visual_seek_ms,
        audio_seek_ms=start_ms,
        duration_ms=actual_duration_ms,
        subtitle_path=subtitle_path,
        concat_input=concat_input,
    )
    run_ffmpeg(args, project.id)
    result = _result(output_path, start_ms, actual_duration_ms, signature, skipped=False)
    manifest = _load_manifest(manifest_path)
    manifest[signature] = result
    write_json_atomic(manifest_path, manifest)
    return result


def build_preview_args(
    visual_path: Path,
    audio_path: Path,
    output_path: Path,
    *,
    visual_seek_ms: int,
    audio_seek_ms: int,
    duration_ms: int,
    subtitle_path: Path | None,
    concat_input: bool = False,
) -> list[str]:
    duration = duration_ms / 1000
    filters = ["scale=960:-2:flags=lanczos"]
    if subtitle_path:
        filters.append(final_renderer.subtitle_filter(subtitle_path))
    args = [
        "-y",
        "-ss",
        f"{visual_seek_ms / 1000:.3f}",
    ]
    if concat_input:
        args.extend(["-f", "concat", "-safe", "0"])
    args.extend(
        [
            "-i",
            str(visual_path),
            "-ss",
            f"{audio_seek_ms / 1000:.3f}",
            "-i",
            str(audio_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-t",
            f"{duration:.3f}",
            "-vf",
            ",".join(filters),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "28",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    return args


def _preview_visual_source(
    session: Session,
    project: Project,
    base_dir: Path,
    preview_dir: Path,
    start_ms: int,
    duration_ms: int,
) -> tuple[Path, int, bool, list[Path]]:
    visual_track = base_dir / "renders" / "visual_track.mp4"
    if visual_track.is_file():
        return visual_track, start_ms, False, [visual_track]
    end_ms = start_ms + duration_ms
    scenes = list(
        session.exec(
            select(VisualScene)
            .where(
                VisualScene.project_id == project.id,
                VisualScene.end_ms > start_ms,
                VisualScene.start_ms < end_ms,
            )
            .order_by(VisualScene.scene_index)
        ).all()
    )
    if not scenes:
        raise ValueError("Preview range does not contain visual scenes")
    scene_paths = []
    for scene in scenes:
        result = scene_renderer.render_scene(session, project, scene)
        scene_paths.append(Path(result["path"]))
    source_path = preview_dir / f"source_{start_ms}_{duration_ms}.txt"
    write_text_atomic(
        source_path,
        "\n".join("file '" + path.as_posix().replace("'", "'\\''") + "'" for path in scene_paths),
    )
    return source_path, start_ms - scenes[0].start_ms, True, scene_paths


def _write_preview_subtitles(
    cues: list[SubtitleCue],
    preview_dir: Path,
    start_ms: int,
    duration_ms: int,
    signature: str,
) -> Path | None:
    if not cues:
        return None
    blocks = []
    for index, cue in enumerate(cues, start=1):
        cue_start = max(0, cue.start_ms - start_ms) / 1000
        cue_end = min(duration_ms, cue.end_ms - start_ms) / 1000
        blocks.append(
            f"{index}\n{seconds_to_srt_time(cue_start)} --> "
            f"{seconds_to_srt_time(cue_end)}\n{cue.text.strip()}"
        )
    path = preview_dir / f"range_{signature[:12]}.srt"
    write_text_atomic(path, "\n\n".join(blocks) + "\n")
    return path


def _preview_cues(
    session: Session, project_id: str, start_ms: int, duration_ms: int
) -> list[SubtitleCue]:
    end_ms = start_ms + duration_ms
    return list(
        session.exec(
            select(SubtitleCue)
            .where(
                SubtitleCue.project_id == project_id,
                SubtitleCue.end_ms > start_ms,
                SubtitleCue.start_ms < end_ms,
            )
            .order_by(SubtitleCue.start_ms)
        ).all()
    )


def _preview_signature(
    visual_paths: list[Path],
    audio_path: Path,
    start_ms: int,
    duration_ms: int,
    cues: list[SubtitleCue],
) -> str:
    payload = {
        "version": 1,
        "start_ms": start_ms,
        "duration_ms": duration_ms,
        "visual": [_file_identity(path) for path in visual_paths],
        "audio": _file_identity(audio_path),
        "subtitles": [
            {
                "id": cue.id,
                "start_ms": cue.start_ms,
                "end_ms": cue.end_ms,
                "text": cue.text,
            }
            for cue in cues
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _file_identity(path: Path) -> dict:
    stat = path.stat()
    return {"path": str(path.resolve()), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _load_manifest(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _result(
    path: Path,
    start_ms: int,
    duration_ms: int,
    signature: str,
    *,
    skipped: bool,
) -> dict:
    return {
        "path": str(path),
        "start_ms": start_ms,
        "duration_ms": duration_ms,
        "signature": signature,
        "skipped": skipped,
        "draft": True,
    }
