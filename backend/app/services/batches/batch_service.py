import json
import uuid
from pathlib import Path
from typing import BinaryIO

from sqlmodel import Session, select

from app.models.batch import BatchItem, BatchJob
from app.models.project import Project
from app.infrastructure.project_layout import get_output_stem, safe_filename_stem
from app.services.projects import project_service
from app.shared.time import utc_now_iso


MAX_SCRIPT_FILES = 100
MAX_SCRIPT_BYTES = 5 * 1024 * 1024
SUPPORTED_SCRIPT_EXTENSIONS = {".txt", ".md"}
DEFAULT_TTS_ENGINE = project_service.DEFAULT_TTS_ENGINE


def decode_script_file(filename: str, content: bytes) -> str:
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_SCRIPT_EXTENSIONS:
        raise ValueError(f"不支持的逐字稿格式：{filename}")
    if not content:
        raise ValueError(f"逐字稿为空：{filename}")
    if len(content) > MAX_SCRIPT_BYTES:
        raise ValueError(f"逐字稿超过 5 MB：{filename}")
    if b"\x00" in content:
        raise ValueError(f"逐字稿看起来不是文本文件：{filename}")

    for encoding in ("utf-8-sig", "gb18030", "big5"):
        try:
            text = content.decode(encoding)
        except UnicodeDecodeError:
            continue
        if text.strip():
            return text
    raise ValueError(f"无法识别逐字稿编码：{filename}")


def create_batch(
    session: Session,
    *,
    name: str,
    scripts: list[tuple[str, str]],
    reference_audio: BinaryIO,
    reference_audio_filename: str,
    output_dir: str,
    media_video_dir: str,
    include_video: bool,
    continue_on_error: bool,
    tts_engine: str = DEFAULT_TTS_ENGINE,
    reference_audio_text: str = "",
) -> BatchJob:
    if not scripts:
        raise ValueError("请至少上传一份逐字稿")
    if len(scripts) > MAX_SCRIPT_FILES:
        raise ValueError(f"一次最多上传 {MAX_SCRIPT_FILES} 份逐字稿")
    if Path(reference_audio_filename).suffix.lower() not in {".wav", ".mp3", ".flac", ".m4a"}:
        raise ValueError("参考音频必须是 WAV、MP3、FLAC 或 M4A")
    normalized_tts_engine = tts_engine.strip().lower()
    if normalized_tts_engine not in project_service.SUPPORTED_TTS_ENGINES:
        raise ValueError("不支持的 TTS 引擎")

    output_root = Path(output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    video_root = Path(media_video_dir).expanduser().resolve() if media_video_dir.strip() else None
    if include_video and (video_root is None or not video_root.is_dir()):
        raise ValueError("生成视频时必须选择有效的素材视频目录")

    now = utc_now_iso()
    batch = BatchJob(
        id=uuid.uuid4().hex[:12],
        name=name.strip() or "批量生成",
        total=len(scripts),
        config_json=json.dumps(
            {
                "output_dir": str(output_root),
                "media_video_dir": str(video_root) if video_root else "",
                "include_video": include_video,
                "continue_on_error": continue_on_error,
                "reference_audio_filename": reference_audio_filename,
                "tts_engine": normalized_tts_engine,
                "reference_audio_text": reference_audio_text.strip(),
            },
            ensure_ascii=False,
        ),
        created_at=now,
        updated_at=now,
    )
    session.add(batch)
    session.commit()

    used_stems = _existing_output_stems(session, output_root)
    used_project_names: set[str] = set()
    for order_index, (filename, text) in enumerate(scripts, start=1):
        script_stem = safe_filename_stem(Path(filename).stem)
        project_name = _unique_name(script_stem, used_project_names)
        stem = _unique_stem(f"{batch.name}_{script_stem}", used_stems, output_root)
        project = project_service.create_project(
            session,
            project_name,
            {
                "tts_engine": normalized_tts_engine,
                "reference_audio_text": reference_audio_text.strip(),
            },
        )
        project_service.update_project_settings(
            session,
            project,
            project_name,
            str(output_root),
            stem,
            str(video_root) if video_root else "",
            normalized_tts_engine,
            reference_audio_text,
        )
        reference_audio.seek(0)
        project_service.save_reference_audio(
            session,
            project,
            reference_audio,
            reference_audio_filename,
        )
        project_service.save_script(session, project, text)
        session.add(
            BatchItem(
                id=uuid.uuid4().hex[:12],
                batch_id=batch.id,
                project_id=project.id,
                order_index=order_index,
                original_filename=filename,
                current_stage="segmenting",
            )
        )
        session.commit()

    return get_batch(session, batch.id) or batch


def list_batches(session: Session) -> list[BatchJob]:
    return list(session.exec(select(BatchJob).order_by(BatchJob.created_at.desc())).all())


def get_batch(session: Session, batch_id: str) -> BatchJob | None:
    return session.get(BatchJob, batch_id)


def get_batch_items(session: Session, batch_id: str) -> list[BatchItem]:
    return list(
        session.exec(
            select(BatchItem)
            .where(BatchItem.batch_id == batch_id)
            .order_by(BatchItem.order_index)
        ).all()
    )


def serialize_batch(session: Session, batch: BatchJob, include_items: bool = True) -> dict:
    data = batch.model_dump()
    if not include_items:
        return data
    items = []
    for item in get_batch_items(session, batch.id):
        row = item.model_dump()
        project = session.get(Project, item.project_id)
        row["project_name"] = project.name if project else item.original_filename
        row["project_status"] = project.status if project else "missing"
        items.append(row)
    data["items"] = items
    return data


def start_batch(session: Session, batch: BatchJob) -> BatchJob:
    if batch.status == "running":
        return batch
    pending = get_batch_items(session, batch.id)
    if not any(item.status == "pending" for item in pending):
        raise ValueError("批次中没有等待执行的文件")
    batch.status = "queued"
    batch.finished_at = None
    batch.updated_at = utc_now_iso()
    session.add(batch)
    session.commit()
    session.refresh(batch)
    return batch


def pause_batch(session: Session, batch: BatchJob) -> BatchJob:
    if batch.status not in {"queued", "running"}:
        raise ValueError("当前批次不在运行中")
    batch.status = "paused"
    batch.updated_at = utc_now_iso()
    session.add(batch)
    session.commit()
    session.refresh(batch)
    return batch


def retry_item(session: Session, batch: BatchJob, item_id: str) -> BatchItem:
    item = session.get(BatchItem, item_id)
    if not item or item.batch_id != batch.id:
        raise ValueError("批次文件不存在")
    if item.status != "failed":
        raise ValueError("只有失败的文件可以重试")
    item.status = "pending"
    item.error_message = None
    item.started_at = None
    item.finished_at = None
    item.updated_at = utc_now_iso()
    session.add(item)
    refresh_counts(session, batch)
    batch.status = "queued"
    batch.finished_at = None
    batch.updated_at = utc_now_iso()
    session.add(batch)
    session.commit()
    session.refresh(item)
    return item


def refresh_counts(session: Session, batch: BatchJob) -> None:
    items = get_batch_items(session, batch.id)
    batch.completed = sum(item.status == "completed" for item in items)
    batch.failed = sum(item.status == "failed" for item in items)


def _existing_output_stems(session: Session, output_root: Path) -> set[str]:
    stems: set[str] = set()
    for project in session.exec(select(Project)).all():
        if not project.output_dir:
            continue
        if Path(project.output_dir).expanduser().resolve() == output_root:
            stems.add(get_output_stem(project).lower())
    return stems


def _unique_stem(filename_stem: str, used_stems: set[str], output_root: Path) -> str:
    base = safe_filename_stem(filename_stem)
    candidate = base
    suffix = 2
    while candidate.lower() in used_stems or _output_stem_exists(output_root, candidate):
        candidate = safe_filename_stem(f"{base}-{suffix}")
        suffix += 1
    used_stems.add(candidate.lower())
    return candidate


def _unique_name(name: str, used_names: set[str]) -> str:
    candidate = name
    suffix = 2
    while candidate.lower() in used_names:
        candidate = safe_filename_stem(f"{name}-{suffix}")
        suffix += 1
    used_names.add(candidate.lower())
    return candidate


def _output_stem_exists(output_root: Path, stem: str) -> bool:
    return any(
        path.exists()
        for path in (
            output_root / stem,
            output_root / f"{stem}.wav",
            output_root / f"{stem}.srt",
            output_root / f"{stem}_en.srt",
            output_root / f"{stem}.mp4",
        )
    )
