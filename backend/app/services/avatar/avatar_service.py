from __future__ import annotations

import json
import logging
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import BinaryIO

from PIL import Image, ImageChops, ImageStat
from sqlalchemy import func
from sqlmodel import Session, select

from app.config import get_settings
from app.database import engine
from app.infrastructure.ffmpeg import (
    detect_silence_intervals,
    probe_duration,
    probe_media,
    run_ffmpeg,
)
from app.infrastructure.gpu_resource import exclusive_gpu
from app.integrations.avatar.duix_client import DuixClient
from app.models.avatar import AvatarClip, AvatarGenerationTask, AvatarProfile
from app.shared.time import utc_now_iso


logger = logging.getLogger(__name__)
_worker_thread: threading.Thread | None = None
_worker_lock = threading.Lock()
_wake_event = threading.Event()

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}


def _root() -> Path:
    root = get_settings().duix_host_shared_dir.resolve() / "tubeaiflow"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_filename(filename: str, extensions: set[str]) -> str:
    name = Path(filename or "upload").name
    suffix = Path(name).suffix.lower()
    if suffix not in extensions:
        raise ValueError(f"不支持的文件格式：{suffix or '无扩展名'}")
    return f"{uuid.uuid4().hex}{suffix}"


def _save_upload(source: BinaryIO, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as target:
        shutil.copyfileobj(source, target, length=1024 * 1024)


def create_profile(session: Session, *, name: str, source: BinaryIO, filename: str) -> AvatarProfile:
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("人物形象名称不能为空")
    profile_id = uuid.uuid4().hex[:12]
    path = _root() / "profiles" / profile_id / _safe_filename(filename, VIDEO_EXTENSIONS)
    _save_upload(source, path)
    try:
        media = probe_media(path)
        if not media.get("video_stream_count"):
            raise ValueError("上传文件不包含可用的视频轨道")
        profile = AvatarProfile(
            id=profile_id,
            name=clean_name,
            template_video_path=str(path),
            duration_ms=media.get("duration_ms"),
            width=media.get("width"),
            height=media.get("height"),
        )
        session.add(profile)
        session.commit()
        session.refresh(profile)
        return profile
    except Exception:
        path.unlink(missing_ok=True)
        raise


def list_profiles(session: Session) -> list[AvatarProfile]:
    return list(
        session.exec(
            select(AvatarProfile)
            .where(AvatarProfile.enabled == True)  # noqa: E712
            .order_by(AvatarProfile.created_at.desc())
        ).all()
    )


def delete_profile(session: Session, profile: AvatarProfile) -> None:
    referenced = session.exec(
        select(func.count(AvatarGenerationTask.id)).where(
            AvatarGenerationTask.avatar_profile_id == profile.id
        )
    ).one()
    if referenced:
        raise ValueError("该人物形象已有生成记录，不能删除；可以保留用于任务追溯")
    path = Path(profile.template_video_path)
    session.delete(profile)
    session.commit()
    if path.is_file():
        path.unlink()


def enqueue_task(
    session: Session,
    *,
    avatar_profile_id: str,
    source: BinaryIO,
    filename: str,
    output_filename: str,
    chunk_seconds: int,
    context_ms: int = 800,
) -> AvatarGenerationTask:
    profile = session.get(AvatarProfile, avatar_profile_id)
    if not profile or not profile.enabled:
        raise ValueError("请选择有效的参考人物形象")
    chunk_seconds = int(chunk_seconds)
    if not 300 <= chunk_seconds <= 600:
        raise ValueError("章节级单段时长必须在 5～10 分钟之间")
    context_ms = int(context_ms)
    if not 300 <= context_ms <= 1200:
        raise ValueError("口型预滚上下文必须在 300～1200 毫秒之间")
    clean_output = Path(output_filename.strip() or "avatar-video.mp4").name
    if Path(clean_output).suffix.lower() != ".mp4":
        clean_output = f"{Path(clean_output).stem}.mp4"
    task_id = uuid.uuid4().hex
    audio_path = _root() / "tasks" / task_id / "input" / _safe_filename(filename, AUDIO_EXTENSIONS)
    _save_upload(source, audio_path)
    try:
        duration = probe_duration(audio_path)
        if duration <= 0:
            raise ValueError("音频时长无效")
        last_sequence = session.exec(select(func.max(AvatarGenerationTask.queue_sequence))).one()
        task = AvatarGenerationTask(
            id=task_id,
            avatar_profile_id=profile.id,
            audio_path=str(audio_path),
            output_filename=clean_output,
            chunk_seconds=chunk_seconds,
            context_ms=context_ms,
            audio_duration_ms=round(duration * 1000),
            queue_sequence=int(last_sequence or 0) + 1,
        )
        session.add(task)
        session.commit()
        session.refresh(task)
        return task
    except Exception:
        audio_path.unlink(missing_ok=True)
        raise


def serialize_task(session: Session, task: AvatarGenerationTask) -> dict:
    clips = list(
        session.exec(
            select(AvatarClip)
            .where(AvatarClip.task_id == task.id)
            .order_by(AvatarClip.clip_index)
        ).all()
    )
    data = task.model_dump()
    data["clips"] = [clip.model_dump() for clip in clips]
    data["continuity_report"] = None
    if task.continuity_report_path and Path(task.continuity_report_path).is_file():
        try:
            report = json.loads(Path(task.continuity_report_path).read_text(encoding="utf-8"))
            if isinstance(report, dict):
                data["continuity_report"] = report
        except (OSError, json.JSONDecodeError):
            logger.exception("Failed to read avatar continuity report for task %s", task.id)
    data["queue_position"] = None
    if task.status == "queued":
        ahead = session.exec(
            select(func.count(AvatarGenerationTask.id)).where(
                AvatarGenerationTask.status == "queued",
                AvatarGenerationTask.queue_sequence < task.queue_sequence,
            )
        ).one()
        running = session.exec(
            select(func.count(AvatarGenerationTask.id)).where(
                AvatarGenerationTask.status == "running"
            )
        ).one()
        data["queue_position"] = int(ahead or 0) + int(running or 0) + 1
    return data


def list_tasks(session: Session, limit: int = 100) -> list[dict]:
    tasks = list(
        session.exec(
            select(AvatarGenerationTask)
            .order_by(AvatarGenerationTask.queue_sequence.desc())
            .limit(limit)
        ).all()
    )
    return [serialize_task(session, task) for task in tasks]


def retry_task(session: Session, task: AvatarGenerationTask) -> AvatarGenerationTask:
    if task.status != "failed":
        raise ValueError("只有失败的数字人任务可以重试")
    clips = list(
        session.exec(
            select(AvatarClip)
            .where(AvatarClip.task_id == task.id)
            .order_by(AvatarClip.clip_index)
        ).all()
    )
    for clip in clips:
        if clip.status == "ready" and clip.output_path and Path(clip.output_path).is_file():
            continue
        clip.status = "generating" if DuixClient().expected_result_path(clip.duix_task_code).is_file() else "pending"
        clip.progress = 0
        clip.error_message = None
        clip.updated_at = utc_now_iso()
        session.add(clip)
    last_sequence = session.exec(select(func.max(AvatarGenerationTask.queue_sequence))).one()
    task.status = "queued"
    task.queue_sequence = int(last_sequence or 0) + 1
    task.completed_chunks = sum(1 for clip in clips if clip.status == "ready")
    task.progress = task.completed_chunks / max(1, task.total_chunks) * 100
    task.current_chunk = None
    task.error_message = None
    task.finished_at = None
    task.updated_at = utc_now_iso()
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def _chunk_bounds(
    duration_ms: int,
    target_seconds: int,
    silence_intervals: list[tuple[float, float]] | None = None,
    *,
    minimum_seconds: int = 30,
    maximum_seconds: int = 90,
) -> list[tuple[int, int]]:
    """Choose contiguous chunks, preferring silence centres near the target length."""
    if duration_ms <= 0:
        return []
    target_ms = target_seconds * 1000
    minimum_ms = minimum_seconds * 1000
    maximum_ms = maximum_seconds * 1000
    if not 0 < minimum_ms <= target_ms <= maximum_ms:
        raise ValueError("分段时长范围无效")
    silence_centres = sorted(
        round(((start + end) / 2) * 1000)
        for start, end in (silence_intervals or [])
        if end > start
    )
    boundaries = [0]
    while duration_ms - boundaries[-1] > maximum_ms:
        start = boundaries[-1]
        target = start + target_ms
        lower = start + minimum_ms
        upper = min(start + maximum_ms, duration_ms - minimum_ms)
        candidates = [point for point in silence_centres if lower <= point <= upper]
        boundary = min(candidates, key=lambda point: abs(point - target)) if candidates else min(target, upper)
        if boundary <= start:
            break
        boundaries.append(boundary)
    boundaries.append(duration_ms)
    return list(zip(boundaries, boundaries[1:]))


def _generation_window(
    start_ms: int,
    end_ms: int,
    duration_ms: int,
    context_ms: int,
) -> tuple[int, int, int, int]:
    generation_start_ms = max(0, start_ms - context_ms)
    generation_end_ms = min(duration_ms, end_ms + context_ms)
    trim_start_ms = start_ms - generation_start_ms
    trim_end_ms = trim_start_ms + (end_ms - start_ms)
    return generation_start_ms, generation_end_ms, trim_start_ms, trim_end_ms


def _prepare_clips(session: Session, task: AvatarGenerationTask) -> list[AvatarClip]:
    existing = list(
        session.exec(
            select(AvatarClip)
            .where(AvatarClip.task_id == task.id)
            .order_by(AvatarClip.clip_index)
        ).all()
    )
    if existing:
        return existing
    try:
        silences = detect_silence_intervals(Path(task.audio_path))
    except RuntimeError:
        logger.exception("Silence detection failed for avatar task %s; using timed boundaries", task.id)
        silences = []
    if task.chunk_seconds <= 90:
        # Resume old tasks created before chapter-level generation was introduced.
        bounds = _chunk_bounds(task.audio_duration_ms, task.chunk_seconds, silences)
    else:
        bounds = _chunk_bounds(
            task.audio_duration_ms,
            task.chunk_seconds,
            silences,
            minimum_seconds=300,
            maximum_seconds=600,
        )
    clips_dir = Path(task.audio_path).parents[1] / "chunks"
    clips_dir.mkdir(parents=True, exist_ok=True)
    clips = []
    for index, (start_ms, end_ms) in enumerate(bounds, 1):
        generation_start_ms, generation_end_ms, trim_start_ms, trim_end_ms = (
            _generation_window(
                start_ms,
                end_ms,
                task.audio_duration_ms,
                task.context_ms,
            )
        )
        audio_path = clips_dir / f"clip_{index:04d}.wav"
        run_ffmpeg([
            "-y", "-ss", f"{generation_start_ms / 1000:.3f}",
            "-t", f"{(generation_end_ms - generation_start_ms) / 1000:.3f}",
            "-i", task.audio_path, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
            str(audio_path),
        ])
        clip = AvatarClip(
            id=uuid.uuid4().hex,
            task_id=task.id,
            clip_index=index,
            start_ms=start_ms,
            end_ms=end_ms,
            generation_start_ms=generation_start_ms,
            generation_end_ms=generation_end_ms,
            trim_start_ms=trim_start_ms,
            trim_end_ms=trim_end_ms,
            audio_path=str(audio_path),
            duix_task_code=f"taf-{task.id[:16]}-{index:04d}",
        )
        session.add(clip)
        clips.append(clip)
    task.total_chunks = len(clips)
    task.updated_at = utc_now_iso()
    session.add(task)
    session.commit()
    return clips


def _update_clip_progress(task_id: str, clip_id: str, remote_progress: float) -> None:
    with Session(engine) as session:
        task = session.get(AvatarGenerationTask, task_id)
        clip = session.get(AvatarClip, clip_id)
        if not task or not clip:
            return
        clip.status = "generating"
        clip.progress = max(0, min(100, remote_progress))
        clip.updated_at = utc_now_iso()
        task.progress = ((task.completed_chunks + clip.progress / 100) / max(1, task.total_chunks)) * 100
        task.updated_at = utc_now_iso()
        session.add(clip)
        session.add(task)
        session.commit()


def _generate_clip(session: Session, task: AvatarGenerationTask, profile: AvatarProfile, clip: AvatarClip) -> None:
    output_path = Path(task.audio_path).parents[1] / "clips" / f"clip_{clip.clip_index:04d}.mp4"
    if clip.status == "ready" and output_path.is_file():
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    client = DuixClient()
    generation_seconds = max(1, clip.generation_end_ms - clip.generation_start_ms) / 1000
    # Local 5090 measurements are roughly 54–62x slower than real time. Keep a
    # conservative 70x budget plus final encoding time, even if an older saved
    # system setting still contains the previous four-hour timeout.
    client.task_timeout = min(86_400, max(client.task_timeout, generation_seconds * 70 + 1800))
    resume_remote = clip.status in {"submitted", "generating"}
    clip.status = "submitted"
    clip.error_message = None
    clip.updated_at = utc_now_iso()
    session.add(clip)
    session.commit()
    cached_result = client.expected_result_path(clip.duix_task_code)
    result = {"host_result_path": str(cached_result)} if cached_result.is_file() else None
    if result is None:
        with exclusive_gpu(f"duix-avatar:{task.id}:{clip.clip_index}"):
            if resume_remote:
                try:
                    result = client.wait_for_result(
                        clip.duix_task_code,
                        lambda value: _update_clip_progress(task.id, clip.id, value),
                    )
                except RuntimeError as exc:
                    if "任务不存在" not in str(exc):
                        raise
            if result is None:
                for attempt in range(120):
                    try:
                        client.submit(
                            audio_path=Path(clip.audio_path),
                            video_path=Path(profile.template_video_path),
                            code=clip.duix_task_code,
                        )
                        break
                    except RuntimeError as exc:
                        if "正忙" not in str(exc) or attempt == 119:
                            raise
                        time.sleep(client.poll_interval)
                result = client.wait_for_result(
                    clip.duix_task_code,
                    lambda value: _update_clip_progress(task.id, clip.id, value),
                )
    source = Path(result["host_result_path"])
    if not source.is_file():
        raise RuntimeError(f"Duix 输出文件不存在：{source}")
    raw_actual_ms = round(probe_duration(source) * 1000)
    expected_generation_ms = clip.generation_end_ms - clip.generation_start_ms
    if abs(raw_actual_ms - expected_generation_ms) > 100:
        raise RuntimeError(
            f"数字人片段 {clip.clip_index} 原始输出时长误差 "
            f"{raw_actual_ms - expected_generation_ms}ms，超过 100ms"
        )
    core_duration_ms = clip.end_ms - clip.start_ms
    run_ffmpeg([
        "-y", "-i", str(source), "-ss", f"{clip.trim_start_ms / 1000:.3f}",
        "-t", f"{core_duration_ms / 1000:.3f}", "-an", "-vf", "fps=30,format=yuv420p",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(output_path),
    ])
    actual_ms = round(probe_duration(output_path) * 1000)
    if abs(actual_ms - core_duration_ms) > 100:
        raise RuntimeError(
            f"数字人片段 {clip.clip_index} 核心区时长误差 "
            f"{actual_ms - core_duration_ms}ms，超过 100ms"
        )
    clip.status = "ready"
    clip.progress = 100
    clip.output_path = str(output_path)
    clip.actual_duration_ms = actual_ms
    clip.updated_at = utc_now_iso()
    session.add(clip)
    session.commit()


def _image_similarity(left: Image.Image, right: Image.Image) -> float:
    difference = ImageChops.difference(left, right)
    mean = ImageStat.Stat(difference).mean
    return max(0.0, min(1.0, 1 - (sum(mean) / (len(mean) * 255))))


def _frame_similarity(left_path: Path, right_path: Path) -> tuple[float, float, float]:
    with Image.open(left_path) as left_image, Image.open(right_path) as right_image:
        left = left_image.convert("RGB").resize((160, 90))
        right = right_image.convert("RGB").resize((160, 90))
        full_similarity = _image_similarity(left, right)
        # Duix templates normally keep the speaker near the centre. Weight the
        # centre/lower-face area more heavily so a static background cannot hide
        # an obvious mouth or chin jump.
        mouth_box = (40, 32, 120, 78)
        mouth_similarity = _image_similarity(left.crop(mouth_box), right.crop(mouth_box))
    weighted = (full_similarity * 0.3) + (mouth_similarity * 0.7)
    return full_similarity, mouth_similarity, weighted


def _write_continuity_report(task: AvatarGenerationTask, clips: list[AvatarClip]) -> Path:
    task_root = Path(task.audio_path).parents[1]
    frame_dir = task_root / "continuity_frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    seams = []
    for left, right in zip(clips, clips[1:]):
        left_path = Path(left.output_path or "")
        right_path = Path(right.output_path or "")
        left_frame = frame_dir / f"seam_{left.clip_index:04d}_last.jpg"
        right_frame = frame_dir / f"seam_{right.clip_index:04d}_first.jpg"
        left_duration = max(0, (left.actual_duration_ms or (left.end_ms - left.start_ms)) - 40)
        run_ffmpeg([
            "-y", "-ss", f"{left_duration / 1000:.3f}", "-i", str(left_path),
            "-frames:v", "1", "-q:v", "2", str(left_frame),
        ])
        run_ffmpeg([
            "-y", "-ss", "0", "-i", str(right_path),
            "-frames:v", "1", "-q:v", "2", str(right_frame),
        ])
        full_similarity, mouth_similarity, weighted_similarity = _frame_similarity(
            left_frame, right_frame
        )
        similarity = round(weighted_similarity, 4)
        severity = "ok" if similarity >= 0.85 else "warning" if similarity >= 0.72 else "high"
        seams.append({
            "left_clip": left.clip_index,
            "right_clip": right.clip_index,
            "timeline_ms": left.end_ms,
            "similarity": similarity,
            "full_frame_similarity": round(full_similarity, 4),
            "mouth_region_similarity": round(mouth_similarity, 4),
            "severity": severity,
            "cut_reason": "silence_preferred_boundary",
        })
    report = {
        "task_id": task.id,
        "context_ms": task.context_ms,
        "seam_count": len(seams),
        "warning_count": sum(1 for seam in seams if seam["severity"] != "ok"),
        "seams": seams,
    }
    report_path = task_root / "continuity_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path


def _compose_final(task: AvatarGenerationTask, clips: list[AvatarClip]) -> Path:
    task_root = Path(task.audio_path).parents[1]
    concat_file = task_root / "concat.txt"
    lines = []
    for clip in clips:
        if not clip.output_path or not Path(clip.output_path).is_file():
            raise RuntimeError(f"数字人片段 {clip.clip_index} 尚未生成")
        escaped = str(Path(clip.output_path).resolve()).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    concat_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    silent_video = task_root / "avatar_video_only.mp4"
    final_path = task_root / task.output_filename
    run_ffmpeg(["-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(silent_video)])
    run_ffmpeg([
        "-y", "-i", str(silent_video), "-i", task.audio_path,
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-ar", "48000",
        "-t", f"{task.audio_duration_ms / 1000:.3f}", "-movflags", "+faststart", str(final_path),
    ])
    if not final_path.is_file():
        raise RuntimeError("最终数字人视频未生成")
    return final_path


def process_next_task() -> bool:
    with Session(engine) as session:
        task = session.exec(
            select(AvatarGenerationTask)
            .where(AvatarGenerationTask.status == "queued")
            .order_by(AvatarGenerationTask.queue_sequence)
        ).first()
        if not task:
            return False
        task.status = "running"
        task.started_at = task.started_at or utc_now_iso()
        task.updated_at = utc_now_iso()
        task.error_message = None
        session.add(task)
        session.commit()
        task_id = task.id
        try:
            profile = session.get(AvatarProfile, task.avatar_profile_id)
            if not profile or not Path(profile.template_video_path).is_file():
                raise RuntimeError("参考人物形象文件不存在")
            clips = _prepare_clips(session, task)
            for clip in clips:
                task.current_chunk = clip.clip_index
                task.updated_at = utc_now_iso()
                session.add(task)
                session.commit()
                _generate_clip(session, task, profile, clip)
                task.completed_chunks = sum(1 for item in clips if item.status == "ready")
                task.progress = task.completed_chunks / max(1, task.total_chunks) * 100
                session.add(task)
                session.commit()
            report_path = _write_continuity_report(task, clips)
            final_path = _compose_final(task, clips)
            task.status = "completed"
            task.progress = 100
            task.result_path = str(final_path)
            task.continuity_report_path = str(report_path)
            task.current_chunk = None
            task.finished_at = utc_now_iso()
            task.updated_at = task.finished_at
            session.add(task)
            session.commit()
        except Exception as exc:
            logger.exception("Avatar generation task %s failed", task_id)
            session.rollback()
            current = session.get(AvatarGenerationTask, task_id)
            if current:
                current.status = "failed"
                current.error_message = str(exc)[-4000:]
                current.finished_at = utc_now_iso()
                current.updated_at = current.finished_at
                session.add(current)
                session.commit()
        return True


def recover_and_start_worker() -> None:
    with Session(engine) as session:
        tasks = list(
            session.exec(
                select(AvatarGenerationTask).where(AvatarGenerationTask.status == "running")
            ).all()
        )
        for task in tasks:
            task.status = "queued"
            task.error_message = "后端重启，任务已从已完成片段继续排队"
            task.updated_at = utc_now_iso()
            session.add(task)
        session.commit()
    wake_worker()


def wake_worker() -> None:
    global _worker_thread
    with _worker_lock:
        if not _worker_thread or not _worker_thread.is_alive():
            _worker_thread = threading.Thread(target=_worker_loop, name="avatar-worker", daemon=True)
            _worker_thread.start()
    _wake_event.set()


def _worker_loop() -> None:
    while True:
        _wake_event.wait(timeout=2)
        _wake_event.clear()
        try:
            while process_next_task():
                pass
        except Exception:
            logger.exception("Avatar queue failed; it will retry")
