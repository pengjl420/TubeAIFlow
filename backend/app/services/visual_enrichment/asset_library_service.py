from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path

from PIL import Image
from sqlalchemy import delete
from sqlmodel import Session, select

from app.infrastructure.ffmpeg import probe_media
from app.infrastructure.project_layout import load_project_config
from app.models.media import (
    LIBRARY_ROLE_LOCAL_SEMANTIC,
    SELECTION_STAGE_MANUAL_LOCAL_ASSET,
    MediaFile,
    MediaShot,
    SceneAssignment,
    SceneCandidate,
)
from app.models.project import Project
from app.models.storyboard import VisualScene
from app.schemas.storyboard import StoryboardContent
from app.services.rendering import timeline_composer
from app.services.storyboard import scene_workspace_service
from app.shared.time import utc_now_iso


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
LIBRARY_ROLE = LIBRARY_ROLE_LOCAL_SEMANTIC


def scan_project_directory(session: Session, project: Project) -> dict:
    root = project_media_directory(project)
    paths = sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS | IMAGE_EXTENSIONS
    )
    indexed = 0
    skipped = 0
    errors: list[dict] = []
    for path in paths:
        try:
            if _register_file(session, root, path):
                indexed += 1
            else:
                skipped += 1
        except (OSError, RuntimeError, ValueError) as exc:
            errors.append({"path": str(path), "error": str(exc)})
    # A changed library can alter both the available rows and repetition scores.
    session.exec(delete(SceneCandidate).where(SceneCandidate.project_id == project.id))
    session.commit()
    return {
        "root": str(root),
        "discovered": len(paths),
        "indexed": indexed,
        "skipped": skipped,
        "errors": errors,
    }


def scene_candidates(
    session: Session, project: Project, scene_id: str, *, refresh: bool = False
) -> list[dict]:
    scene = _scene(session, project, scene_id)
    root = project_media_directory(project)
    if refresh:
        scan_project_directory(session, project)
    query, query_tokens = _scene_query(scene)
    if not refresh:
        cached = _cached_candidates(session, project, scene, root, query)
        if cached:
            return cached
    shots = _project_library_shots(session, root)
    session.exec(delete(SceneCandidate).where(SceneCandidate.scene_id == scene.id))
    ranked: list[tuple[SceneCandidate, MediaShot, MediaFile]] = []
    used_shot_ids = set(
        session.exec(
            select(SceneAssignment.media_shot_id).where(
                SceneAssignment.project_id == project.id,
                SceneAssignment.scene_id != scene.id,
            )
        ).all()
    )
    for shot, media in shots:
        text_tokens = _tokens(f"{media.filename} {shot.description}")
        try:
            tag_values = json.loads(shot.tags_json or "[]")
        except json.JSONDecodeError:
            tag_values = []
        tag_tokens = _tokens(" ".join(str(value) for value in tag_values))
        text_score = _overlap(query_tokens, text_tokens)
        tag_score = _overlap(query_tokens, tag_tokens)
        technical_score = _technical_score(media)
        repeat_penalty = 0.18 if shot.id in used_shot_ids else 0.0
        total = max(0.0, min(1.0, text_score * 0.55 + tag_score * 0.2 + technical_score * 0.25 - repeat_penalty))
        candidate = SceneCandidate(
            id=f"candidate_{uuid.uuid4().hex}",
            project_id=project.id,
            scene_id=scene.id,
            media_shot_id=shot.id,
            source="local",
            query=query,
            semantic_score=text_score,
            text_score=text_score,
            tag_score=tag_score,
            technical_score=technical_score,
            total_score=total,
            status="RECOMMENDED" if total >= 0.45 else "USABLE" if total >= 0.25 else "LOW_RELEVANCE",
            conflicts_json=json.dumps(["used_in_project"] if repeat_penalty else []),
            selection_stage="local_semantic",
        )
        session.add(candidate)
        ranked.append((candidate, shot, media))
    session.commit()
    ranked.sort(key=lambda item: (-item[0].total_score, item[2].filename.lower()))
    return [_candidate_value(*item) for item in ranked[:50]]


def assign_local_candidate(
    session: Session, project: Project, scene_id: str, candidate_id: str
) -> dict:
    scene = _scene(session, project, scene_id)
    if scene.locked_visual:
        raise ValueError("Scene visual is locked")
    candidate = session.get(SceneCandidate, candidate_id)
    if not candidate or candidate.project_id != project.id or candidate.scene_id != scene.id:
        raise LookupError("Local asset candidate not found")
    shot = session.get(MediaShot, candidate.media_shot_id)
    media = session.get(MediaFile, shot.media_file_id) if shot else None
    if not shot or not media or not Path(media.path).is_file():
        raise ValueError("Local asset file is missing")
    Path(media.path).resolve().relative_to(project_media_directory(project))

    session.exec(delete(SceneAssignment).where(SceneAssignment.scene_id == scene.id))
    duration_ms = scene.end_ms - scene.start_ms
    source_duration = max(0, (shot.end_ms or media.duration_ms or 0) - shot.start_ms)
    if media.media_type == "image":
        display_duration = duration_ms
        playback_speed = 1.0
        trim_end = None
    else:
        if source_duration <= 0:
            raise ValueError("Local video duration is unavailable")
        display_duration = min(duration_ms, round(source_duration / timeline_composer.MIN_PLAYBACK_SPEED))
        playback_speed = max(
            timeline_composer.MIN_PLAYBACK_SPEED,
            min(1.0, source_duration / max(1, display_duration)),
        )
        trim_end = min(source_duration, round(display_duration * playback_speed))
    assignment = SceneAssignment(
        id=f"assignment_{uuid.uuid4().hex}",
        project_id=project.id,
        scene_id=scene.id,
        media_shot_id=shot.id,
        sequence_index=1,
        scene_offset_start_ms=0,
        scene_offset_end_ms=display_duration,
        trim_start_ms=0,
        trim_end_ms=trim_end,
        playback_speed=playback_speed,
        display_duration_ms=display_duration,
        render_mode="image" if media.media_type == "image" else "video",
        motion_type="auto" if media.media_type == "image" else "none",
        selection_stage=SELECTION_STAGE_MANUAL_LOCAL_ASSET,
    )
    session.add(assignment)
    session.commit()
    scene_workspace_service.invalidate_scene_outputs(project, scene)
    return scene_workspace_service.scene_assets(session, project, scene.id)


def project_media_directory(project: Project) -> Path:
    config = load_project_config(project)
    value = str(config.get("media_video_dir") or "").strip()
    if not value:
        raise ValueError("项目尚未配置本地素材目录")
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("本地素材目录不存在")
    return root


def _register_file(session: Session, root: Path, path: Path) -> bool:
    resolved = path.resolve()
    resolved.relative_to(root)
    path_key = hashlib.sha1(str(resolved).encode("utf-8")).hexdigest()
    stat = resolved.stat()
    existing = session.exec(
        select(MediaFile).where(
            MediaFile.provider == "local_library",
            MediaFile.provider_asset_id == path_key,
        )
    ).first()
    if existing:
        try:
            previous_metadata = json.loads(existing.metadata_json or "{}")
        except json.JSONDecodeError:
            previous_metadata = {}
        if (
            existing.size_bytes == stat.st_size
            and previous_metadata.get("mtime_ns") == stat.st_mtime_ns
        ):
            return False
    digest = _sha256(resolved)
    if resolved.suffix.lower() in IMAGE_EXTENSIONS:
        with Image.open(resolved) as image:
            width, height = image.size
        media_type = "image"
        duration_ms = None
        technical = {"width": width, "height": height}
    else:
        technical = probe_media(resolved)
        duration_ms = technical.get("duration_ms")
        width = technical.get("width")
        height = technical.get("height")
        if not duration_ms:
            raise ValueError("无法读取视频时长")
        media_type = "video"
    duplicate = _same_library_content(session, root, digest)
    if duplicate and existing is None:
        return False
    media = existing or MediaFile(
        id=f"local_media_{path_key[:24]}",
        provider="local_library",
        provider_asset_id=path_key,
        path=str(resolved),
        filename=resolved.name,
        media_type=media_type,
        file_hash=digest,
    )
    media.path = str(resolved)
    media.filename = resolved.name
    media.media_type = media_type
    media.file_hash = digest
    media.size_bytes = stat.st_size
    media.duration_ms = duration_ms
    media.width = width
    media.height = height
    media.library_role = LIBRARY_ROLE
    media.status = "ready"
    media.metadata_json = json.dumps(
        {
            "source_directory": str(root),
            "relative_path": str(resolved.relative_to(root)),
            "mtime_ns": stat.st_mtime_ns,
        },
        ensure_ascii=False,
    )
    media.updated_at = utc_now_iso()
    session.add(media)
    session.flush()
    shot = session.exec(
        select(MediaShot).where(MediaShot.media_file_id == media.id)
    ).first()
    if shot is None:
        shot = MediaShot(
            id=f"local_shot_{path_key[:24]}",
            media_file_id=media.id,
            shot_index=1,
        )
    shot.start_ms = 0
    shot.end_ms = duration_ms
    shot.description = resolved.stem.replace("_", " ").replace("-", " ")
    shot.tags_json = json.dumps(sorted(_tokens(resolved.stem)), ensure_ascii=False)
    shot.library_role = LIBRARY_ROLE
    shot.status = "ready"
    shot.technical_json = json.dumps(technical, ensure_ascii=False)
    shot.updated_at = utc_now_iso()
    session.add(shot)
    session.flush()
    return True


def _same_library_content(
    session: Session, root: Path, digest: str
) -> MediaFile | None:
    for media in session.exec(
        select(MediaFile).where(
            MediaFile.provider == "local_library",
            MediaFile.file_hash == digest,
        )
    ).all():
        try:
            metadata = json.loads(media.metadata_json or "{}")
        except json.JSONDecodeError:
            continue
        if Path(str(metadata.get("source_directory") or "")).resolve() == root:
            return media
    return None


def _cached_candidates(
    session: Session,
    project: Project,
    scene: VisualScene,
    root: Path,
    query: str,
) -> list[dict]:
    candidates = list(
        session.exec(
            select(SceneCandidate)
            .where(
                SceneCandidate.project_id == project.id,
                SceneCandidate.scene_id == scene.id,
                SceneCandidate.query == query,
            )
            .order_by(SceneCandidate.total_score.desc())
        ).all()
    )
    values: list[dict] = []
    for candidate in candidates:
        shot = session.get(MediaShot, candidate.media_shot_id)
        media = session.get(MediaFile, shot.media_file_id) if shot else None
        if not shot or not media:
            continue
        try:
            Path(media.path).resolve().relative_to(root)
        except ValueError:
            continue
        values.append(_candidate_value(candidate, shot, media))
        if len(values) == 50:
            break
    return values


def _project_library_shots(session: Session, root: Path) -> list[tuple[MediaShot, MediaFile]]:
    rows = session.exec(
        select(MediaShot, MediaFile)
        .join(MediaFile, MediaFile.id == MediaShot.media_file_id)
        .where(MediaFile.library_role == LIBRARY_ROLE, MediaFile.status == "ready")
    ).all()
    result = []
    for shot, media in rows:
        try:
            Path(media.path).resolve().relative_to(root)
        except ValueError:
            continue
        result.append((shot, media))
    return result


def _scene(session: Session, project: Project, scene_id: str) -> VisualScene:
    scene = session.get(VisualScene, scene_id)
    if not scene or scene.project_id != project.id:
        raise LookupError("Visual scene not found")
    return scene


def _scene_query(scene: VisualScene) -> tuple[str, set[str]]:
    values = [scene.narration]
    if scene.storyboard_json:
        storyboard = StoryboardContent.model_validate_json(scene.storyboard_json)
        values = [
            storyboard.primary_query,
            *storyboard.alternative_queries,
            storyboard.visual_summary,
            *storyboard.entities,
            *storyboard.locations,
            storyboard.mood,
        ]
    query = " ".join(value for value in values if value)
    return query, _tokens(query)


def _tokens(value: str) -> set[str]:
    normalized = value.lower()
    words = set(re.findall(r"[a-z0-9]{2,}|[\u4e00-\u9fff]+", normalized))
    cjk = "".join(re.findall(r"[\u4e00-\u9fff]", normalized))
    words.update(cjk[index:index + 2] for index in range(max(0, len(cjk) - 1)))
    return {word for word in words if word}


def _overlap(expected: set[str], actual: set[str]) -> float:
    return len(expected & actual) / max(1, min(len(expected), 8))


def _technical_score(media: MediaFile) -> float:
    if not media.width or not media.height:
        return 0.2
    aspect = media.width / media.height
    aspect_score = max(0.0, 1.0 - abs(aspect - 16 / 9) / (16 / 9))
    resolution_score = min(1.0, media.width / 1920)
    return aspect_score * 0.65 + resolution_score * 0.35


def _candidate_value(candidate: SceneCandidate, shot: MediaShot, media: MediaFile) -> dict:
    return {
        "id": candidate.id,
        "media_shot_id": shot.id,
        "filename": media.filename,
        "path": media.path,
        "media_type": media.media_type,
        "duration_ms": media.duration_ms,
        "width": media.width,
        "height": media.height,
        "description": shot.description,
        "score": round(candidate.total_score, 4),
        "status": candidate.status,
        "conflicts": json.loads(candidate.conflicts_json or "[]"),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
