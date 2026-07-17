import hashlib
import json
import re
from pathlib import Path
from uuid import uuid4

from sqlmodel import Session, select

from app.infrastructure.ffmpeg import probe_media
from app.models.media import MediaFile, MediaShot
from app.shared.time import utc_now_iso


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
SHOT_TARGET_MS = 12_000
MIN_TAIL_MS = 1_500


def import_directory(session: Session, directory: str) -> dict:
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
            media_file = _create_media_file(path, file_hash)
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


def list_assets(session: Session, limit: int = 200) -> list[dict]:
    media_files = session.exec(
        select(MediaFile).order_by(MediaFile.created_at.desc()).limit(limit)
    ).all()
    result = []
    for media_file in media_files:
        shots = session.exec(
            select(MediaShot)
            .where(MediaShot.media_file_id == media_file.id)
            .order_by(MediaShot.shot_index)
        ).all()
        item = _serialize_media_file(media_file)
        item["shots"] = [_serialize_shot(shot) for shot in shots]
        result.append(item)
    return result


def _create_media_file(path: Path, file_hash: str) -> MediaFile:
    media_type = "video" if path.suffix.lower() in VIDEO_EXTENSIONS else "image"
    metadata = probe_media(path)
    now = utc_now_iso()
    return MediaFile(
        id=f"media_{uuid4().hex}",
        path=str(path),
        filename=path.name,
        media_type=media_type,
        file_hash=file_hash,
        size_bytes=path.stat().st_size,
        duration_ms=metadata.get("duration_ms"),
        width=metadata.get("width"),
        height=metadata.get("height"),
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
        "status": media_file.status,
        "created_at": media_file.created_at,
    }


def _serialize_shot(shot: MediaShot) -> dict:
    return {
        "id": shot.id,
        "shot_index": shot.shot_index,
        "start_ms": shot.start_ms,
        "end_ms": shot.end_ms,
        "description": shot.description,
        "tags": json.loads(shot.tags_json),
        "thumbnail_path": shot.thumbnail_path,
        "status": shot.status,
    }
