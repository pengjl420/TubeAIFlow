import json
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


def write_json_atomic(path: Path, data: Any) -> None:
    encoded = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    write_text_atomic(path, encoded)


def write_text_atomic(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as file:
        file.write(value)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, path)


def write_bytes_atomic(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("wb") as file:
        file.write(value)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, path)


@contextmanager
def atomic_output_path(path: Path) -> Iterator[Path]:
    """Yield a sibling media path and publish it only after successful validation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.stem}.{uuid.uuid4().hex[:8]}.partial{path.suffix}")
    temporary.unlink(missing_ok=True)
    try:
        yield temporary
        if not temporary.is_file() or temporary.stat().st_size <= 0:
            raise RuntimeError(f"Temporary output was not created: {temporary.name}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
