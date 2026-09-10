import logging
import json
import re
import threading
import uuid
from pathlib import Path

from sqlalchemy import func
from sqlmodel import Session, select

from app.database import engine
from app.config import get_settings
from app.infrastructure import process_runner as task_control
from app.infrastructure.logging_config import task_log_context
from app.infrastructure.recycle_bin import move_existing_to_recycle_bin
from app.models.voice_generation import VoiceGenerationTask
from app.services.narration import tts_service, voice_profile_service
from app.shared.time import elapsed_seconds, utc_now_iso


logger = logging.getLogger(__name__)
_worker_thread: threading.Thread | None = None
_worker_lock = threading.Lock()
_queue_state_lock = threading.Lock()
_wake_event = threading.Event()
_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def split_transcript_lines(text: str) -> list[str]:
    """Split only on line breaks; blank lines do not create TTS requests."""
    return [line.strip() for line in str(text or "").splitlines() if line.strip()]


def normalize_output_filename(value: str) -> str:
    filename = Path(str(value or "").strip()).name
    if not filename:
        raise ValueError("请输入输出音频文件名称")
    if _INVALID_FILENAME.search(filename):
        raise ValueError("输出文件名包含不支持的字符")
    if not filename.lower().endswith(".wav"):
        filename += ".wav"
    if len(filename) > 200:
        raise ValueError("输出文件名不能超过 200 个字符")
    if Path(filename).stem.upper() in voice_profile_service.WINDOWS_RESERVED_NAMES:
        raise ValueError("输出文件名是 Windows 保留名称")
    return filename


def enqueue(
    session: Session, *, voice_profile_id: str, text: str, output_filename: str
) -> VoiceGenerationTask:
    profile = voice_profile_service.get_profile(session, voice_profile_id.strip())
    if not profile:
        raise ValueError("请选择有效的参考音色")
    if not Path(profile.reference_audio_path).is_file():
        raise ValueError("所选参考音色的音频文件不存在")
    content = text.strip()
    if not content:
        raise ValueError("请输入需要生成配音的文本")
    if len(content) > 50000:
        raise ValueError("单次配音文本不能超过 50000 个字符")
    last_sequence = session.exec(select(func.max(VoiceGenerationTask.queue_sequence))).one()
    task = VoiceGenerationTask(
        id=uuid.uuid4().hex,
        voice_profile_id=profile.id,
        voice_profile_name=profile.name,
        text=content,
        output_filename=normalize_output_filename(output_filename),
        queue_sequence=int(last_sequence or 0) + 1,
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    with task_log_context(task.id):
        logger.info("Voice generation queued: segments=%s", len(split_transcript_lines(content)))
    return task


def serialize_task(session: Session, task: VoiceGenerationTask) -> dict:
    with task_log_context(task.id):
        queue_position = None
        if task.status == "queued":
            ahead = session.exec(
                select(func.count(VoiceGenerationTask.id)).where(
                    VoiceGenerationTask.status == "queued",
                    VoiceGenerationTask.queue_sequence < task.queue_sequence,
                )
            ).one()
            running = session.exec(
                select(func.count(VoiceGenerationTask.id)).where(
                    VoiceGenerationTask.status == "running"
                )
            ).one()
            queue_position = int(ahead or 0) + int(running or 0) + 1
        data = task.model_dump()
        profile = voice_profile_service.get_profile(session, task.voice_profile_id)
        profile_config = voice_profile_service.load_profile_config(profile) if profile else {}
        data["tts_engine"] = str(profile_config.get("tts_engine") or "qwen3_tts")
        data["language"] = voice_profile_service.profile_language(profile_config)
        data["queue_position"] = queue_position
        data["duration_seconds"] = elapsed_seconds(task.started_at, task.finished_at)
        data["audio_url"] = (
            f"/api/tools/voice-generation/tasks/{task.id}/audio" if task.output_path else None
        )
        lines = split_transcript_lines(task.text)
        output_dir = get_settings().workspace_dir / "voice_generations" / task.id
        manifest_path = output_dir / "segments.json"
        segment_results = []
        if manifest_path.is_file():
            try:
                loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    segment_results = loaded
            except (OSError, json.JSONDecodeError):
                logger.warning("Cannot read voice generation segment manifest: %s", manifest_path)
        result_by_index = {
            int(item.get("index", 0)): item for item in segment_results if isinstance(item, dict)
        }
        stem = Path(task.output_filename).stem
        data["segments"] = [
            {
                "index": index,
                "text": line,
                "filename": f"{stem}_{index:04d}.wav",
                "duration": result_by_index.get(index, {}).get("duration"),
                "audio_url": (
                    f"/api/tools/voice-generation/tasks/{task.id}/segments/{index}/audio"
                    if index in result_by_index
                    else None
                ),
            }
            for index, line in enumerate(lines, start=1)
        ]
        data["segment_count"] = len(lines)
        return data


def list_tasks(session: Session, limit: int = 100) -> list[dict]:
    tasks = session.exec(
        select(VoiceGenerationTask).order_by(VoiceGenerationTask.queue_sequence.desc()).limit(limit)
    ).all()
    return [serialize_task(session, task) for task in tasks]


def pause_task(session: Session, task: VoiceGenerationTask) -> VoiceGenerationTask:
    with task_log_context(task.id):
        with _queue_state_lock:
            session.refresh(task)
            if task.status not in {"queued", "running"}:
                raise ValueError("只有排队中或生成中的任务可以暂停")
            was_running = task.status == "running"
            task.status = "paused"
            task.updated_at = utc_now_iso()
            session.add(task)
            session.commit()
            session.refresh(task)
        if was_running:
            task_control.cancel(_runtime_id(task.id))
        logger.info("Voice generation paused")
        return task


def resume_task(session: Session, task: VoiceGenerationTask) -> VoiceGenerationTask:
    with task_log_context(task.id):
        with _queue_state_lock:
            session.refresh(task)
            if task.status != "paused":
                raise ValueError("只有已暂停的任务可以恢复")
            last_sequence = session.exec(select(func.max(VoiceGenerationTask.queue_sequence))).one()
            task.status = "queued"
            task.queue_sequence = int(last_sequence or 0) + 1
            task.started_at = None
            task.finished_at = None
            task.error_message = None
            task.updated_at = utc_now_iso()
            session.add(task)
            session.commit()
            session.refresh(task)
        logger.info("Voice generation resumed and requeued")
        return task


def delete_task(session: Session, task: VoiceGenerationTask) -> list[str]:
    with task_log_context(task.id):
        with _queue_state_lock:
            session.refresh(task)
            if task.status == "running" or task_control.status(_runtime_id(task.id))["running"]:
                raise ValueError("任务进程尚未停止，请先暂停并等待片刻后再删除")
            output_dir = (get_settings().workspace_dir / "voice_generations" / task.id).resolve()
            recycled = move_existing_to_recycle_bin([output_dir])
            session.delete(task)
            session.commit()
        logger.info("Voice generation deleted")
        return recycled


def recover_interrupted_tasks(session: Session) -> int:
    tasks = list(
        session.exec(
            select(VoiceGenerationTask).where(VoiceGenerationTask.status == "running")
        ).all()
    )
    now = utc_now_iso()
    for task in tasks:
        task.status = "queued"
        task.started_at = None
        task.error_message = "后端重启，任务已自动重新排队"
        task.updated_at = now
        session.add(task)
        with task_log_context(task.id):
            logger.warning("Voice generation interrupted by restart; requeued")
    if tasks:
        session.commit()
    return len(tasks)


def process_next_task() -> bool:
    with Session(engine) as session:
        with _queue_state_lock:
            task = session.exec(
                select(VoiceGenerationTask)
                .where(VoiceGenerationTask.status == "queued")
                .order_by(VoiceGenerationTask.queue_sequence, VoiceGenerationTask.created_at)
            ).first()
            if not task:
                return False
            now = utc_now_iso()
            task.status = "running"
            task.attempt_count += 1
            task.started_at = now
            task.updated_at = now
            task.error_message = None
            session.add(task)
            session.commit()
            task_id = task.id
        with task_log_context(task_id):
            session.refresh(task)
            if task.status == "paused":
                return True
            logger.info("Voice generation started: attempt=%s", task.attempt_count)
            try:
                profile = voice_profile_service.get_profile(session, task.voice_profile_id)
                if not profile:
                    raise ValueError("参考音色已被删除")
                with task_control.controlled(_runtime_id(task.id), "tts"):
                    result = tts_service.generate_segmented_audio(
                        task.id, profile, split_transcript_lines(task.text), task.output_filename
                    )
            except Exception as exc:
                if not isinstance(exc, task_control.TaskCancelledError):
                    logger.exception("Voice generation failed: attempt=%s", task.attempt_count)
                else:
                    logger.info("Voice generation stopped")
                session.rollback()
                current = session.get(VoiceGenerationTask, task_id)
                if current:
                    finished = utc_now_iso()
                    if current.status != "paused":
                        current.status = "failed"
                        current.error_message = str(exc)[-4000:]
                        current.finished_at = finished
                    current.updated_at = finished
                    session.add(current)
                    session.commit()
            else:
                current = session.get(VoiceGenerationTask, task_id)
                if current:
                    finished = utc_now_iso()
                    if current.status != "paused":
                        current.status = "completed"
                        current.output_path = result["output_path"]
                        current.duration = result["duration"]
                        current.finished_at = finished
                    current.updated_at = finished
                    session.add(current)
                    session.commit()
            logger.info(
                "Voice generation attempt finished: status=%s",
                current.status if current else "deleted",
            )
            return True


def wake_worker() -> None:
    global _worker_thread
    with _worker_lock:
        if not _worker_thread or not _worker_thread.is_alive():
            _worker_thread = threading.Thread(
                target=_worker_loop, name="voice-generation-worker", daemon=True
            )
            _worker_thread.start()
    _wake_event.set()


def recover_and_start_worker() -> None:
    with Session(engine) as session:
        recover_interrupted_tasks(session)
    wake_worker()


def _runtime_id(task_id: str) -> str:
    return f"voice-generation-{task_id}"


def _worker_loop() -> None:
    while True:
        _wake_event.wait(timeout=2)
        _wake_event.clear()
        try:
            while process_next_task():
                pass
        except Exception:
            logger.exception("Voice generation queue failed; it will retry")
