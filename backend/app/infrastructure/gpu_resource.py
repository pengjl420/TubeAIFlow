from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from app.config import get_settings


logger = logging.getLogger(__name__)
_PROCESS_LOCK = threading.RLock()
_LOCAL = threading.local()


@contextmanager
def exclusive_gpu(owner: str) -> Iterator[None]:
    """Serialize every local GPU model user, including across backend processes.

    The lock is re-entrant within one thread so a complete business operation can
    hold the GPU while lower-level embedding calls use the same guard. Cleanup
    callbacks run before the next waiter is admitted, which prevents a cached
    model from remaining in VRAM when another model starts.
    """
    name = str(owner or "gpu-job").strip() or "gpu-job"
    outermost = getattr(_LOCAL, "depth", 0) == 0
    lock_file: BinaryIO | None = None
    started_waiting = time.monotonic()

    _PROCESS_LOCK.acquire()
    try:
        if outermost:
            lock_file = _acquire_file_lock(_lock_path())
            _LOCAL.owner = name
            _LOCAL.cleanups = {}
            waited = time.monotonic() - started_waiting
            logger.info("GPU acquired by %s after %.3fs", name, waited)
        _LOCAL.depth = getattr(_LOCAL, "depth", 0) + 1
        try:
            yield
        finally:
            _LOCAL.depth -= 1
            if outermost:
                _run_cleanups(name)
                logger.info("GPU released by %s", name)
                _LOCAL.owner = None
                _LOCAL.cleanups = {}
                _release_file_lock(lock_file)
                lock_file = None
    finally:
        if lock_file is not None:
            _release_file_lock(lock_file)
        _PROCESS_LOCK.release()


def defer_cleanup(key: str, callback: Callable[[], None]) -> None:
    """Run a deduplicated cleanup before the current outer GPU lease ends."""
    if getattr(_LOCAL, "depth", 0) <= 0:
        raise RuntimeError("GPU cleanup must be registered inside exclusive_gpu")
    cleanups = getattr(_LOCAL, "cleanups", None)
    if cleanups is None:
        cleanups = {}
        _LOCAL.cleanups = cleanups
    cleanups[str(key)] = callback


def _run_cleanups(owner: str) -> None:
    cleanups = getattr(_LOCAL, "cleanups", {})
    for key, callback in reversed(list(cleanups.items())):
        try:
            callback()
        except Exception:
            logger.exception("GPU cleanup %s failed for %s", key, owner)


def _lock_path() -> Path:
    return get_settings().workspace_dir / ".runtime" / "gpu-exclusive.lock"


def _acquire_file_lock(path: Path) -> BinaryIO:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = path.open("a+b")
    lock_file.seek(0, os.SEEK_END)
    if lock_file.tell() == 0:
        lock_file.write(b"\n")
        lock_file.flush()

    while True:
        lock_file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return lock_file
        except (OSError, BlockingIOError):
            time.sleep(0.1)


def _release_file_lock(lock_file: BinaryIO | None) -> None:
    if lock_file is None:
        return
    try:
        lock_file.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    finally:
        lock_file.close()
