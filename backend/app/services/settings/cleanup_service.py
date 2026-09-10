"""Local daily retention of archived logs and completed standalone voice tasks."""

import json
import logging
import re
import shutil
import stat
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlmodel import Session, select

from app.config import get_settings
from app.database import engine
from app.infrastructure import process_runner
from app.models.voice_generation import VoiceGenerationTask
from app.services.narration import voice_generation_queue


logger = logging.getLogger(__name__)
_worker_thread: threading.Thread | None = None
_last_error: str | None = None


def get_status(now: datetime | None = None) -> dict:
    settings = get_settings()
    now = now or datetime.now().astimezone()
    state = None
    state_error = None
    try:
        path = checked_path(
            settings.workspace_dir / ".runtime" / "cleanup-state.json", settings.workspace_dir
        )
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError("Invalid cleanup state")
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        state = None
        state_error = "无法读取上次清理记录，请查看引擎日志"
    hour, minute = map(int, settings.cleanup_daily_time.split(":"))
    due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    latest = due if now >= due else due - timedelta(days=1)
    pending = (
        settings.cleanup_enabled
        and (state or {}).get("last_due_date", "") < latest.date().isoformat()
    )
    next_run = now if pending else due if now < due else due + timedelta(days=1)
    return {
        "enabled": settings.cleanup_enabled,
        "retention_days": settings.cleanup_retention_days,
        "daily_time": settings.cleanup_daily_time,
        "completed_voice_tasks": settings.cleanup_completed_voice_tasks,
        "worker_alive": bool(_worker_thread and _worker_thread.is_alive()),
        "catchup_pending": bool(pending),
        "next_run_at": next_run.isoformat() if settings.cleanup_enabled else None,
        "last_run": state,
        "error": state_error or _last_error,
    }


def checked_path(path: Path, root: Path) -> Path:
    """Reject traversal, symlinks and Windows junctions before any deletion."""
    root = root.absolute()
    path = path.absolute()
    if path == root or not path.is_relative_to(root):
        raise ValueError("Cleanup path is outside its managed directory")
    for part in (path, *path.parents):
        reparse = (
            part.exists()
            and getattr(part.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        )
        if part.is_symlink() or reparse:
            raise ValueError("Cleanup does not follow links or junctions")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Cleanup path escaped its managed directory")
    return path


def remove_tree(path: Path, root: Path) -> None:
    path = checked_path(path, root)
    if not path.exists():
        return
    # Validate the entire tree before recursive deletion, including junctions.
    pending = [path]
    while pending:
        directory = pending.pop()
        for child in directory.iterdir():
            checked_path(child, root)
            if child.is_dir():
                pending.append(child)
    shutil.rmtree(path)


def expired(value: str | None, cutoff: datetime) -> bool:
    if not value:
        return False
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp.replace(tzinfo=stamp.tzinfo or timezone.utc) < cutoff
    except ValueError:
        return False


def clean_logs(directory: Path, root: Path, cutoff: datetime, pattern: str) -> int:
    checked_path(directory, root)
    if not directory.exists():
        return 0
    count = 0
    for path in directory.iterdir():
        if not re.fullmatch(pattern, path.name):
            continue
        checked_path(path, root)
        if path.is_file() and path.stat().st_mtime < cutoff.timestamp():
            path.unlink()
            count += 1
    return count


def run_cleanup(session: Session, settings, now: datetime) -> dict:
    root = settings.workspace_dir.expanduser().absolute()
    cutoff = now.astimezone(timezone.utc) - timedelta(days=settings.cleanup_retention_days)
    report = {"deleted_tasks": 0, "deleted_logs": 0, "errors": 0}
    try:
        report["deleted_logs"] += clean_logs(root / "logs", root, cutoff, r"engine\.log\.\d+")
    except (OSError, ValueError):
        report["errors"] += 1
        logger.exception("CLEANUP_LOG_FAILED")
    tasks = session.exec(
        select(VoiceGenerationTask).where(VoiceGenerationTask.status == "completed")
    ).all()
    for task in tasks:
        try:
            # Use the same lock as pause/resume/delete and queue dispatch.
            with voice_generation_queue._queue_state_lock:
                session.refresh(task)
                if (
                    task.status != "completed"
                    or process_runner.status(voice_generation_queue._runtime_id(task.id))["running"]
                ):
                    continue
                if not re.fullmatch(r"[A-Za-z0-9_-]+", task.id):
                    raise ValueError("Invalid voice task directory name")
                directory = root / "voice_generations" / task.id
                checked_path(directory, root / "voice_generations")
                if settings.cleanup_completed_voice_tasks and expired(task.finished_at, cutoff):
                    remove_tree(directory, root / "voice_generations")
                    session.delete(task)
                    session.commit()
                    report["deleted_tasks"] += 1
                else:
                    report["deleted_logs"] += clean_logs(
                        directory / "logs", root, cutoff, r"(?:tts|error)(?:_[\w.-]+)?\.log"
                    )
        except Exception:
            session.rollback()
            report["errors"] += 1
            logger.exception("CLEANUP_TASK_FAILED task_id=%s", task.id)
    return report


def run_if_due(now: datetime | None = None) -> dict | None:
    settings = get_settings()
    if not settings.cleanup_enabled:
        return None
    now = now or datetime.now().astimezone()
    hour, minute = map(int, settings.cleanup_daily_time.split(":"))
    due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now < due:
        due -= timedelta(days=1)
    state_path = settings.workspace_dir / ".runtime" / "cleanup-state.json"
    checked_path(state_path, settings.workspace_dir)
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        state = {}
    if state.get("last_due_date", "") >= due.date().isoformat():
        return None
    with Session(engine) as session:
        report = run_cleanup(session, settings, now)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_path.with_suffix(".tmp")
    checked_path(temporary, settings.workspace_dir)
    temporary.write_text(
        json.dumps(
            {
                "last_due_date": due.date().isoformat(),
                "finished_at": now.isoformat(),
                **report,
            }
        ),
        encoding="utf-8",
    )
    temporary.replace(state_path)
    logger.info("Daily cleanup finished: %s", report)
    return report


def start_worker() -> tuple[threading.Event, threading.Thread]:
    global _worker_thread
    stop = threading.Event()

    def worker():
        global _last_error
        while not stop.is_set():
            try:
                run_if_due()
                _last_error = None
            except Exception:
                _last_error = "自动清理执行失败，将于下一次检查重试；详情见引擎日志"
                logger.exception("CLEANUP_SCHEDULE_FAILED")
            stop.wait(60)

    thread = threading.Thread(target=worker, name="daily-cleanup", daemon=True)
    _worker_thread = thread
    thread.start()
    return stop, thread
