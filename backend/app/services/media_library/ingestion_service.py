import hashlib
import json
import re
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete, func, or_
from sqlmodel import Session, select

from app.config import get_settings
from app.infrastructure import gpu_resource
from app.infrastructure.asset_layout import media_preview_dir
from app.infrastructure.ffmpeg import probe_media, run_ffmpeg
from app.integrations.vision.embedding import MODEL_NAME
from app.integrations.vision.vector_index import remove_shot, remove_shots, upsert_shot
from app.models.media import (
    LIBRARY_ROLE_PROJECT_GENERATED,
    LIBRARY_ROLE_SEMANTIC,
    LIBRARY_ROLES,
    MediaFile,
    MediaKeyframe,
    MediaShot,
    SceneAssignment,
    SceneCandidate,
)
from app.models.storyboard import VisualScene
from app.schemas.media import AssetUpdateRequest, RemoteMediaCandidate
from app.shared.time import utc_now_iso


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
SHOT_TARGET_MS = 12_000
MIN_TAIL_MS = 1_500


def current_vector_model() -> str:
    return MODEL_NAME


def import_directory(
    session: Session,
    directory: str,
    library_role: str = LIBRARY_ROLE_SEMANTIC,
    fallback_category: str = "",
    mood: str = "",
) -> dict:
    if library_role not in LIBRARY_ROLES:
        raise ValueError(f"未知素材角色：{library_role}")
    root = Path(directory).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"素材目录不存在：{root}")

    supported = VIDEO_EXTENSIONS | IMAGE_EXTENSIONS
    paths = sorted(
        path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in supported
    )
    imported = []
    skipped = []
    errors = []
    for path in paths:
        try:
            file_hash = _sha256(path)
            existing = session.exec(
                select(MediaFile).where(MediaFile.file_hash == file_hash)
            ).first()
            if existing:
                skipped.append({"path": str(path), "reason": "duplicate", "media_id": existing.id})
                continue
            media_file = _create_media_file(
                path,
                file_hash,
                library_role=library_role,
                fallback_category=fallback_category,
                mood=mood,
            )
            session.add(media_file)
            for shot in _create_shots(media_file):
                session.add(shot)
            imported.append(_serialize_media_file(media_file))
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            errors.append({"path": str(path), "error": str(exc)})
    session.commit()
    return {
        "directory": str(root),
        "discovered": len(paths),
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
    }


def import_remote_asset(
    session: Session,
    path: Path,
    candidate: RemoteMediaCandidate,
) -> tuple[MediaFile, bool]:
    existing = session.exec(
        select(MediaFile).where(
            MediaFile.provider == candidate.provider,
            MediaFile.provider_asset_id == candidate.asset_id,
        )
    ).first()
    if existing:
        return existing, False

    file_hash = _sha256(path)
    duplicate = session.exec(select(MediaFile).where(MediaFile.file_hash == file_hash)).first()
    if duplicate:
        return duplicate, False

    media_file = _create_media_file(
        path,
        file_hash,
        provider=candidate.provider,
        provider_asset_id=candidate.asset_id,
        source_metadata=candidate.model_dump(mode="json"),
        library_role=LIBRARY_ROLE_SEMANTIC,
    )
    description = " ".join([candidate.title, candidate.query]).strip()
    tags = list(dict.fromkeys([*candidate.tags, *_tags(description)]))
    shots = _create_shots(media_file)
    for shot in shots:
        shot.description = description or shot.description
        shot.tags_json = json.dumps(tags, ensure_ascii=False)
    session.add(media_file)
    session.add_all(shots)
    session.commit()
    return media_file, True


def import_uploaded_asset(session: Session, path: Path) -> tuple[MediaFile, bool]:
    """Register one user-uploaded file in the global semantic media library."""
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError(f"上传素材不存在：{resolved}")
    if resolved.suffix.lower() not in VIDEO_EXTENSIONS | IMAGE_EXTENSIONS:
        raise ValueError("仅支持 MP4、MOV、MKV、WebM、AVI、M4V、JPG、PNG、WebP 或 BMP 素材")

    file_hash = _sha256(resolved)
    existing = session.exec(select(MediaFile).where(MediaFile.file_hash == file_hash)).first()
    if existing:
        return existing, False

    media_file = _create_media_file(
        resolved,
        file_hash,
        provider="manual_upload",
        library_role=LIBRARY_ROLE_SEMANTIC,
    )
    session.add(media_file)
    session.add_all(_create_shots(media_file))
    session.commit()
    session.refresh(media_file)
    return media_file, True


def list_assets(
    session: Session,
    limit: int = 200,
    library_role: str | None = None,
) -> list[dict]:
    statement = select(MediaFile)
    if library_role is None:
        statement = statement.where(MediaFile.library_role != LIBRARY_ROLE_PROJECT_GENERATED)
    if library_role:
        if library_role not in LIBRARY_ROLES:
            raise ValueError(f"未知素材角色：{library_role}")
        statement = statement.where(MediaFile.library_role == library_role)
    media_files = session.exec(
        statement.order_by(MediaFile.created_at.desc()).limit(limit)
    ).all()
    result = []
    for media_file in media_files:
        shots = session.exec(
            select(MediaShot)
            .where(MediaShot.media_file_id == media_file.id)
            .order_by(MediaShot.shot_index)
        ).all()
        item = _serialize_media_file(media_file)
        item["shots"] = [serialize_shot(session, shot) for shot in shots]
        result.append(item)
    return result


def list_asset_page(
    session: Session,
    page: int = 1,
    page_size: int = 24,
    library_role: str | None = None,
    search: str = "",
) -> dict:
    if library_role and library_role not in LIBRARY_ROLES:
        raise ValueError(f"未知素材角色：{library_role}")

    filters = []
    if library_role is None:
        filters.append(MediaFile.library_role != LIBRARY_ROLE_PROJECT_GENERATED)
    if library_role:
        filters.append(MediaFile.library_role == library_role)
    normalized_search = search.strip()
    if normalized_search:
        pattern = f"%{normalized_search}%"
        filters.append(
            or_(
                MediaFile.filename.ilike(pattern),
                MediaFile.path.ilike(pattern),
                MediaFile.provider.ilike(pattern),
                MediaFile.fallback_category.ilike(pattern),
                MediaFile.mood.ilike(pattern),
            )
        )

    count_statement = select(func.count()).select_from(MediaFile)
    page_statement = select(MediaFile)
    for condition in filters:
        count_statement = count_statement.where(condition)
        page_statement = page_statement.where(condition)

    total = int(session.exec(count_statement).one())
    media_files = session.exec(
        page_statement
        .order_by(MediaFile.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    assets = []
    for media_file in media_files:
        shots = session.exec(
            select(MediaShot)
            .where(MediaShot.media_file_id == media_file.id)
            .order_by(MediaShot.shot_index)
        ).all()
        item = _serialize_media_file(media_file)
        item["shots"] = [serialize_shot(session, shot) for shot in shots]
        assets.append(item)

    return {
        "assets": assets,
        "page": page,
        "page_size": page_size,
        "total": total,
        "summary": _asset_library_summary(session),
    }


def _asset_library_summary(session: Session) -> dict:
    asset_count = int(session.exec(
        select(func.count()).select_from(MediaFile).where(
            MediaFile.library_role != LIBRARY_ROLE_PROJECT_GENERATED
        )
    ).one())
    shot_count = int(session.exec(
        select(func.count()).select_from(MediaShot).where(
            MediaShot.library_role != LIBRARY_ROLE_PROJECT_GENERATED
        )
    ).one())
    semantic_asset_count = int(session.exec(
        select(func.count())
        .select_from(MediaFile)
        .where(MediaFile.library_role == LIBRARY_ROLE_SEMANTIC)
    ).one())
    indexed_shot_count = int(session.exec(
        select(func.count())
        .select_from(MediaShot)
        .where(MediaShot.vector_id.is_not(None))
        .where(func.json_extract(MediaShot.technical_json, "$.vector_model") == MODEL_NAME)
    ).one())
    preview_shot_count = int(session.exec(
        select(func.count())
        .select_from(MediaShot)
        .where(MediaShot.thumbnail_path.is_not(None))
    ).one())
    return {
        "asset_count": asset_count,
        "shot_count": shot_count,
        "semantic_asset_count": semantic_asset_count,
        "indexed_shot_count": indexed_shot_count,
        "preview_shot_count": preview_shot_count,
    }


def get_asset(session: Session, media_id: str) -> dict:
    media_file = session.get(MediaFile, media_id)
    if not media_file:
        raise ValueError("素材不存在")
    shots = session.exec(
        select(MediaShot)
        .where(MediaShot.media_file_id == media_file.id)
        .order_by(MediaShot.shot_index)
    ).all()
    item = _serialize_media_file(media_file)
    item["shots"] = [serialize_shot(session, shot) for shot in shots]
    return item


def clear_search_cache(session: Session) -> dict:
    """Clear disposable provider query responses without touching source media or indexes."""
    from app.models.media import MediaQueryCache

    rows = list(session.exec(select(MediaQueryCache)).all())
    for row in rows:
        session.delete(row)
    session.commit()
    return {"deleted_query_cache_entries": len(rows), "source_files_preserved": True}


def update_asset(
    session: Session,
    media_id: str,
    payload: AssetUpdateRequest,
) -> dict:
    media_file = session.get(MediaFile, media_id)
    if not media_file:
        raise ValueError("素材不存在")
    shots = session.exec(
        select(MediaShot).where(MediaShot.media_file_id == media_file.id)
    ).all()
    media_file.library_role = payload.library_role
    media_file.fallback_category = payload.fallback_category
    media_file.mood = payload.mood
    media_file.review_status = payload.review_status
    media_file.enabled = payload.enabled
    media_file.updated_at = utc_now_iso()
    session.add(media_file)
    for shot in shots:
        shot.library_role = payload.library_role
        shot.fallback_category = payload.fallback_category
        shot.mood = payload.mood
        if payload.library_role != LIBRARY_ROLE_SEMANTIC and shot.vector_id is not None:
            remove_shot(shot.id)
            shot.vector_id = None
            technical = _safe_json_object(shot.technical_json)
            technical["vector_model"] = None
            shot.technical_json = json.dumps(technical, ensure_ascii=False)
        shot.updated_at = utc_now_iso()
        session.add(shot)
    session.commit()
    return get_asset(session, media_id)


def delete_assets(session: Session, media_ids: list[str]) -> dict:
    """Delete library records and generated previews while preserving source files."""
    requested_ids = list(dict.fromkeys(media_ids))
    media_files = session.exec(select(MediaFile).where(MediaFile.id.in_(requested_ids))).all()
    found_ids = {media_file.id for media_file in media_files}
    missing_ids = [media_id for media_id in requested_ids if media_id not in found_ids]
    if not media_files:
        return {
            "deleted_ids": [],
            "missing_ids": missing_ids,
            "deleted_preview_files": 0,
            "source_files_preserved": 0,
        }

    shot_rows = session.exec(
        select(MediaShot).where(MediaShot.media_file_id.in_(found_ids))
    ).all()
    shot_ids = [shot.id for shot in shot_rows]
    keyframes = (
        session.exec(select(MediaKeyframe).where(MediaKeyframe.media_shot_id.in_(shot_ids))).all()
        if shot_ids else []
    )

    deleted_preview_files = 0
    for media_file in media_files:
        media_shots = [shot for shot in shot_rows if shot.media_file_id == media_file.id]
        media_keyframes = [frame for frame in keyframes if frame.media_shot_id in {shot.id for shot in media_shots}]
        deleted_preview_files += _delete_preview_files(media_file, media_shots, media_keyframes)

    remove_shots(shot_ids)

    affected_scene_ids: set[str] = set()
    if shot_ids:
        assignments = session.exec(
            select(SceneAssignment).where(SceneAssignment.media_shot_id.in_(shot_ids))
        ).all()
        affected_scene_ids = {assignment.scene_id for assignment in assignments}
        session.exec(delete(SceneAssignment).where(SceneAssignment.media_shot_id.in_(shot_ids)))
        session.exec(delete(SceneCandidate).where(SceneCandidate.media_shot_id.in_(shot_ids)))
        session.exec(delete(MediaKeyframe).where(MediaKeyframe.media_shot_id.in_(shot_ids)))
        session.exec(delete(MediaShot).where(MediaShot.id.in_(shot_ids)))
    for scene_id in affected_scene_ids:
        scene = session.get(VisualScene, scene_id)
        if scene:
            scene.status = "generated"
            session.add(scene)
    session.exec(delete(MediaFile).where(MediaFile.id.in_(found_ids)))
    session.commit()
    return {
        "deleted_ids": [media_id for media_id in requested_ids if media_id in found_ids],
        "missing_ids": missing_ids,
        "deleted_preview_files": deleted_preview_files,
        "source_files_preserved": len(media_files),
    }


def _delete_preview_files(
    media_file: MediaFile,
    shots: list[MediaShot],
    keyframes: list[MediaKeyframe],
) -> int:
    preview_root = media_preview_dir(media_file.id, media_file.provider, get_settings())
    source_path = Path(media_file.path).resolve()
    candidates = {frame.path for frame in keyframes}
    candidates.update(shot.thumbnail_path for shot in shots if shot.thumbnail_path)
    deleted = 0
    for value in candidates:
        path = Path(value).resolve()
        if path == source_path or not path.is_relative_to(preview_root):
            continue
        if path.is_file():
            path.unlink()
            deleted += 1

    directories = sorted(
        {Path(value).resolve().parent for value in candidates if value},
        key=lambda path: len(path.parts),
        reverse=True,
    )
    directories.append(preview_root)
    for directory in directories:
        if directory.is_relative_to(preview_root) and directory.is_dir():
            try:
                directory.rmdir()
            except OSError:
                pass
    return deleted


def ingest_asset(session: Session, media_id: str) -> dict:
    """Generate review frames and a persistent retrieval vector for every shot."""
    media_file = session.get(MediaFile, media_id)
    if not media_file:
        raise ValueError("素材不存在")
    source_path = Path(media_file.path)
    if not source_path.is_file():
        raise ValueError(f"素材文件不存在：{source_path}")

    shots = session.exec(
        select(MediaShot)
        .where(MediaShot.media_file_id == media_file.id)
        .order_by(MediaShot.shot_index)
    ).all()
    errors = []
    owner = f"asset-vectorization:media:{media_file.id}"
    with gpu_resource.exclusive_gpu(owner):
        for shot in shots:
            try:
                _ingest_shot(session, media_file, shot, source_path)
            except (OSError, RuntimeError, ValueError) as exc:
                shot.status = "error"
                technical = _safe_json_object(shot.technical_json)
                technical["ingestion_error"] = str(exc)
                shot.technical_json = json.dumps(technical, ensure_ascii=False)
                shot.updated_at = utc_now_iso()
                session.add(shot)
                errors.append({"shot_id": shot.id, "error": str(exc)})
    media_file.status = "ready" if len(errors) < len(shots) else "error"
    media_file.updated_at = utc_now_iso()
    session.add(media_file)
    session.commit()
    return {"asset": get_asset(session, media_id), "errors": errors}


def _create_media_file(
    path: Path,
    file_hash: str,
    provider: str = "local",
    provider_asset_id: str | None = None,
    source_metadata: dict | None = None,
    library_role: str = LIBRARY_ROLE_SEMANTIC,
    fallback_category: str = "",
    mood: str = "",
) -> MediaFile:
    media_type = "video" if path.suffix.lower() in VIDEO_EXTENSIONS else "image"
    metadata = probe_media(path)
    if source_metadata:
        metadata["source"] = source_metadata
    now = utc_now_iso()
    return MediaFile(
        id=f"media_{uuid4().hex}",
        provider=provider,
        provider_asset_id=provider_asset_id,
        path=str(path),
        filename=path.name,
        media_type=media_type,
        file_hash=file_hash,
        size_bytes=path.stat().st_size,
        duration_ms=metadata.get("duration_ms"),
        width=metadata.get("width"),
        height=metadata.get("height"),
        library_role=library_role,
        fallback_category=fallback_category,
        mood=mood,
        metadata_json=json.dumps(metadata, ensure_ascii=False),
        created_at=now,
        updated_at=now,
    )


def _create_shots(media_file: MediaFile) -> list[MediaShot]:
    description = re.sub(r"[_\-.]+", " ", Path(media_file.filename).stem).strip()
    tags = _tags(description)
    ranges = _shot_ranges(media_file.media_type, media_file.duration_ms)
    technical = {
        "width": media_file.width,
        "height": media_file.height,
        "media_type": media_file.media_type,
    }
    now = utc_now_iso()
    return [
        MediaShot(
            id=f"shot_{uuid4().hex}",
            media_file_id=media_file.id,
            shot_index=index,
            start_ms=start_ms,
            end_ms=end_ms,
            description=description,
            tags_json=json.dumps(tags, ensure_ascii=False),
            library_role=media_file.library_role,
            fallback_category=media_file.fallback_category,
            mood=media_file.mood,
            technical_json=json.dumps(technical, ensure_ascii=False),
            created_at=now,
            updated_at=now,
        )
        for index, (start_ms, end_ms) in enumerate(ranges, start=1)
    ]


def _shot_ranges(media_type: str, duration_ms: int | None) -> list[tuple[int, int | None]]:
    if media_type == "image" or not duration_ms:
        return [(0, duration_ms)]
    if duration_ms <= SHOT_TARGET_MS:
        return [(0, duration_ms)]

    ranges: list[tuple[int, int | None]] = []
    start_ms = 0
    while start_ms < duration_ms:
        end_ms = min(start_ms + SHOT_TARGET_MS, duration_ms)
        if duration_ms - end_ms < MIN_TAIL_MS:
            end_ms = duration_ms
        ranges.append((start_ms, end_ms))
        start_ms = end_ms
    return ranges


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tags(description: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+", description.lower())))


def _serialize_media_file(media_file: MediaFile) -> dict:
    return {
        "id": media_file.id,
        "provider": media_file.provider,
        "provider_asset_id": media_file.provider_asset_id,
        "path": media_file.path,
        "filename": media_file.filename,
        "media_type": media_file.media_type,
        "file_hash": media_file.file_hash,
        "size_bytes": media_file.size_bytes,
        "duration_ms": media_file.duration_ms,
        "width": media_file.width,
        "height": media_file.height,
        "library_role": media_file.library_role,
        "fallback_category": media_file.fallback_category,
        "mood": media_file.mood,
        "review_status": media_file.review_status,
        "enabled": media_file.enabled,
        "status": media_file.status,
        "created_at": media_file.created_at,
    }


def _ingest_shot(
    session: Session,
    media_file: MediaFile,
    shot: MediaShot,
    source_path: Path,
) -> None:
    session.exec(delete(MediaKeyframe).where(MediaKeyframe.media_shot_id == shot.id))
    frame_dir = media_preview_dir(media_file.id, media_file.provider, get_settings()) / shot.id
    frame_dir.mkdir(parents=True, exist_ok=True)
    timestamps = _keyframe_timestamps(shot, media_file.media_type)
    frames = []
    now = utc_now_iso()
    for index, timestamp_ms in enumerate(timestamps, start=1):
        frame_path = frame_dir / f"frame_{index:02d}.jpg"
        _extract_frame(source_path, frame_path, timestamp_ms, media_file.media_type)
        frame = MediaKeyframe(
            id=f"keyframe_{uuid4().hex}",
            media_shot_id=shot.id,
            frame_index=index,
            timestamp_ms=timestamp_ms,
            path=str(frame_path),
            created_at=now,
        )
        session.add(frame)
        frames.append(frame)

    searchable_text = " ".join(
        [shot.description, media_file.filename, *json.loads(shot.tags_json)]
    )
    if shot.library_role == LIBRARY_ROLE_SEMANTIC:
        shot.vector_id = upsert_shot(shot.id, searchable_text, [frame.path for frame in frames])
        vector_model = MODEL_NAME
    else:
        remove_shot(shot.id)
        shot.vector_id = None
        vector_model = None
    shot.thumbnail_path = frames[len(frames) // 2].path if frames else None
    shot.status = "ready"
    shot.updated_at = now
    technical = _safe_json_object(shot.technical_json)
    technical.update(
        {
            "keyframe_count": len(frames),
            "vector_model": vector_model,
            "ingestion_error": None,
        }
    )
    shot.technical_json = json.dumps(technical, ensure_ascii=False)
    session.add(shot)


def shot_needs_embedding(shot: MediaShot) -> bool:
    if shot.library_role != LIBRARY_ROLE_SEMANTIC:
        return False
    technical = _safe_json_object(shot.technical_json)
    return shot.vector_id is None or technical.get("vector_model") != MODEL_NAME


def _keyframe_timestamps(shot: MediaShot, media_type: str) -> list[int]:
    if media_type == "image":
        return [0]
    duration_ms = max(1, (shot.end_ms or shot.start_ms + 1) - shot.start_ms)
    if duration_ms <= 4_000:
        count = 3
    elif duration_ms <= 8_000:
        count = 4
    elif duration_ms <= 15_000:
        count = 6
    else:
        count = 8
    return [
        shot.start_ms + min(duration_ms - 1, round(duration_ms * index / (count + 1)))
        for index in range(1, count + 1)
    ]


def _extract_frame(
    source_path: Path,
    destination: Path,
    timestamp_ms: int,
    media_type: str,
) -> None:
    args = ["-y"]
    if media_type == "video":
        args.extend(["-ss", f"{timestamp_ms / 1000:.3f}"])
    args.extend(
        [
            "-i",
            str(source_path),
            "-frames:v",
            "1",
            "-vf",
            "scale=640:-2:force_original_aspect_ratio=decrease",
            "-q:v",
            "3",
            str(destination),
        ]
    )
    run_ffmpeg(args)


def _safe_json_object(value: str) -> dict:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def serialize_shot(session: Session, shot: MediaShot) -> dict:
    keyframes = session.exec(
        select(MediaKeyframe)
        .where(MediaKeyframe.media_shot_id == shot.id)
        .order_by(MediaKeyframe.frame_index)
    ).all()
    technical = _safe_json_object(shot.technical_json)
    return {
        "id": shot.id,
        "shot_index": shot.shot_index,
        "start_ms": shot.start_ms,
        "end_ms": shot.end_ms,
        "description": shot.description,
        "tags": json.loads(shot.tags_json),
        "thumbnail_path": shot.thumbnail_path,
        "thumbnail_url": f"/api/assets/shots/{shot.id}/thumbnail" if shot.thumbnail_path else None,
        "keyframes": [
            {
                "id": frame.id,
                "frame_index": frame.frame_index,
                "timestamp_ms": frame.timestamp_ms,
                "url": f"/api/assets/keyframes/{frame.id}",
            }
            for frame in keyframes
        ],
        "vector_id": shot.vector_id,
        "vector_model": technical.get("vector_model"),
        "library_role": shot.library_role,
        "fallback_category": shot.fallback_category,
        "mood": shot.mood,
        "status": shot.status,
        "technical": technical,
    }
