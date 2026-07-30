from __future__ import annotations

import hashlib
import json
import random
import uuid
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.infrastructure.ffmpeg import probe_media
from app.infrastructure.project_layout import load_project_config
from app.models.media import (
    LIBRARY_ROLE_LOCAL_LANDSCAPE,
    MediaFile,
    MediaShot,
    SceneAssignment,
)
from app.models.project import Project
from app.models.storyboard import VisualScene
from app.schemas.storyboard import StoryboardContent
from app.services.rendering.rough_cut_service import list_rough_cut_video_files


DEFAULT_LANDSCAPE_RATIO = 0.3
SELECTION_STAGE = "local_landscape_mix"


def assign_landscape_scenes(session: Session, project: Project) -> dict:
    """Assign local landscape clips to suitable scenes in a mixed AI workflow."""
    scenes = list(
        session.exec(
            select(VisualScene)
            .where(VisualScene.project_id == project.id)
            .order_by(VisualScene.scene_index)
        ).all()
    )
    if len(scenes) < 2:
        return {"scene_count": len(scenes), "landscape_scene_count": 0, "assignments": []}

    eligible = [
        scene
        for scene in scenes
        if scene.storyboard_json
        and StoryboardContent.model_validate_json(
            scene.storyboard_json
        ).allow_landscape_fallback
    ]
    if not eligible:
        return {"scene_count": len(scenes), "landscape_scene_count": 0, "assignments": []}

    config = load_project_config(project)
    ratio = max(0.05, min(0.8, float(config.get("landscape_mix_ratio", DEFAULT_LANDSCAPE_RATIO))))
    target = min(len(eligible), len(scenes) - 1, max(1, round(len(scenes) * ratio)))
    selected_scenes = _spread_selection(eligible, target)

    media_dir = Path(str(config.get("media_video_dir") or "")).expanduser().resolve()
    if not media_dir.is_dir():
        raise ValueError("Mixed video mode requires a valid landscape material directory")
    source_paths = list_rough_cut_video_files(media_dir)
    ordered_paths = _randomize_for_project(source_paths, project.id)
    used_media_file_ids = set(
        session.exec(
            select(MediaShot.media_file_id)
            .join(
                SceneAssignment,
                SceneAssignment.media_shot_id == MediaShot.id,
            )
            .where(SceneAssignment.project_id == project.id)
        ).all()
    )

    assignments = []
    source_cursor = 0
    for scene in selected_scenes:
        existing = session.exec(
            select(SceneAssignment).where(SceneAssignment.scene_id == scene.id)
        ).first()
        if existing:
            continue
        scene_duration_ms = scene.end_ms - scene.start_ms
        covered_ms = 0
        sequence_index = 1
        attempts = 0
        while covered_ms < scene_duration_ms and attempts < len(ordered_paths):
            source_path = ordered_paths[source_cursor % len(ordered_paths)]
            source_cursor += 1
            attempts += 1
            registered = _register_video(session, source_path)
            if registered is None:
                continue
            media_file, shot = registered
            if media_file.id in used_media_file_ids:
                continue
            available_ms = max(0, (shot.end_ms or media_file.duration_ms or 0) - shot.start_ms)
            if available_ms <= 0:
                continue
            placement_ms = min(scene_duration_ms - covered_ms, round(available_ms / 0.85))
            assignment = SceneAssignment(
                id=f"assignment_{uuid.uuid4().hex}",
                project_id=project.id,
                scene_id=scene.id,
                media_shot_id=shot.id,
                sequence_index=sequence_index,
                scene_offset_start_ms=covered_ms,
                scene_offset_end_ms=covered_ms + placement_ms,
                trim_start_ms=0,
                trim_end_ms=available_ms,
                playback_speed=max(0.85, min(1.0, available_ms / placement_ms)),
                display_duration_ms=placement_ms,
                render_mode="video",
                motion_type="none",
                selection_stage=SELECTION_STAGE,
            )
            session.add(assignment)
            assignments.append(assignment)
            used_media_file_ids.add(media_file.id)
            covered_ms += placement_ms
            sequence_index += 1
        if covered_ms < scene_duration_ms:
            raise ValueError(
                f"Landscape materials cannot cover mixed scene {scene.scene_index}; "
                "add more or longer videos"
            )
    session.commit()
    return {
        "scene_count": len(scenes),
        "landscape_scene_count": len(selected_scenes),
        "assignments": [item.id for item in assignments],
    }


def _spread_selection(scenes: list[VisualScene], target: int) -> list[VisualScene]:
    if target >= len(scenes):
        return scenes
    indexes = []
    for position in range(target):
        index = round((position + 1) * (len(scenes) + 1) / (target + 1)) - 1
        index = max(0, min(len(scenes) - 1, index))
        while index in indexes and index + 1 < len(scenes):
            index += 1
        indexes.append(index)
    return [scenes[index] for index in sorted(set(indexes))]


def _randomize_for_project(paths: list[Path], project_id: str) -> list[Path]:
    shuffled = list(paths)
    seed = int(hashlib.sha256(project_id.encode()).hexdigest()[:16], 16)
    random.Random(seed).shuffle(shuffled)
    return shuffled


def _register_video(session: Session, path: Path) -> tuple[MediaFile, MediaShot] | None:
    resolved = path.resolve()
    provider_asset_id = hashlib.sha1(str(resolved).encode("utf-8")).hexdigest()
    media_file = session.exec(
        select(MediaFile).where(
            MediaFile.provider == "local_landscape",
            MediaFile.provider_asset_id == provider_asset_id,
        )
    ).first()
    if media_file:
        shot = session.exec(
            select(MediaShot).where(MediaShot.media_file_id == media_file.id)
        ).first()
        return (media_file, shot) if shot else None

    try:
        metadata = probe_media(resolved)
    except RuntimeError:
        return None
    duration_ms = metadata.get("duration_ms")
    if not duration_ms or duration_ms <= 0:
        return None
    file_hash = _sha256(resolved)
    media_file = session.exec(
        select(MediaFile).where(MediaFile.file_hash == file_hash)
    ).first()
    if media_file:
        shot = session.exec(
            select(MediaShot).where(MediaShot.media_file_id == media_file.id)
        ).first()
        return (media_file, shot) if shot else None

    media_file = MediaFile(
        id=f"landscape_media_{provider_asset_id[:20]}",
        provider="local_landscape",
        provider_asset_id=provider_asset_id,
        path=str(resolved),
        filename=resolved.name,
        media_type="video",
        file_hash=file_hash,
        size_bytes=resolved.stat().st_size,
        duration_ms=duration_ms,
        width=metadata.get("width"),
        height=metadata.get("height"),
        library_role=LIBRARY_ROLE_LOCAL_LANDSCAPE,
        metadata_json=json.dumps(
            {"source_directory": str(resolved.parent), "local_landscape": True},
            ensure_ascii=False,
        ),
    )
    shot = MediaShot(
        id=f"landscape_shot_{provider_asset_id[:20]}",
        media_file_id=media_file.id,
        shot_index=1,
        start_ms=0,
        end_ms=duration_ms,
        description=resolved.stem,
        tags_json=json.dumps(["landscape", "local", "mixed workflow"]),
        library_role=LIBRARY_ROLE_LOCAL_LANDSCAPE,
        technical_json=json.dumps(metadata, ensure_ascii=False),
    )
    try:
        with session.begin_nested():
            session.add_all([media_file, shot])
            session.flush()
    except IntegrityError:
        media_file = session.exec(
            select(MediaFile).where(MediaFile.file_hash == file_hash)
        ).first()
        if not media_file:
            return None
        shot = session.exec(
            select(MediaShot).where(MediaShot.media_file_id == media_file.id)
        ).first()
        return (media_file, shot) if shot else None
    return media_file, shot


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
