import asyncio
import os
from pathlib import Path
from typing import BinaryIO

import uvicorn

from app.config import BASE_DIR, get_settings


LOCK_PATH = BASE_DIR / "workspace" / "backend.lock"


def main() -> None:
    lock_file = acquire_instance_lock(LOCK_PATH)
    if lock_file is None:
        print("TubeAiFolw Engine is already running. Stop it before starting another instance.")
        return

    try:
        configure_event_loop()
        settings = get_settings()
        port = int(os.environ.get("APP_PORT_OVERRIDE") or settings.app_port)
        uvicorn.run(
            "app.main:app",
            host=settings.app_host,
            port=port,
            # The launcher must own one stable process. Developers can run
            # uvicorn with --reload manually when hot reload is required.
            reload=False,
        )
    finally:
        release_instance_lock(lock_file)


def configure_event_loop() -> None:
    """Avoid noisy Proactor socket shutdown errors in the Windows HTTP server."""
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def acquire_instance_lock(path: Path) -> BinaryIO | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = path.open("a+b")
    lock_file.seek(0, os.SEEK_END)
    if lock_file.tell() == 0:
        lock_file.write(b"\n")
        lock_file.flush()
    lock_file.seek(0)

    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, BlockingIOError):
        lock_file.close()
        return None

    lock_file.seek(0)
    lock_file.truncate()
    lock_file.write(str(os.getpid()).encode("ascii"))
    lock_file.flush()
    return lock_file


def release_instance_lock(lock_file: BinaryIO) -> None:
    try:
        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(b"\n")
        lock_file.flush()
        lock_file.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    finally:
        lock_file.close()


if __name__ == "__main__":
    main()
