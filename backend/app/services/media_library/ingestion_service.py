import hashlib
import json
import re
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete
from sqlmodel import Session, select

from app.config import get_settings
from app.infrastructure.ffmpeg import probe_media, run_ffmpeg
from app.integrations.vision.embedding import MODEL_NAME
from app.integrations.vision.vector_index import upsert_shot
from app.models.media import MediaFile, MediaKeyframe, MediaShot
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
        item["shots"] = [serialize_shot(session, shot) for shot in shots]
        result.append(item)
    return result


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


def _ingest_shot(
    session: Session,
    media_file: MediaFile,
    shot: MediaShot,
    source_path: Path,
) -> None:
    session.exec(delete(MediaKeyframe).where(MediaKeyframe.media_shot_id == shot.id))
    frame_dir = get_settings().workspace_dir / "assets" / media_file.id / shot.id
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
    shot.vector_id = upsert_shot(shot.id, searchable_text)
    shot.thumbnail_path = frames[len(frames) // 2].path if frames else None
    shot.status = "ready"
    shot.updated_at = now
    technical = _safe_json_object(shot.technical_json)
    technical.update(
        {
            "keyframe_count": len(frames),
            "vector_model": MODEL_NAME,
            "ingestion_error": None,
        }
    )
    shot.technical_json = json.dumps(technical, ensure_ascii=False)
    session.add(shot)


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
        "status": shot.status,
        "technical": technical,
    }
