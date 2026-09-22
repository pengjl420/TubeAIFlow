from __future__ import annotations

import hashlib
from pathlib import Path


def file_signature(path: Path, *, strong: bool = False) -> list[int] | dict | None:
    try:
        metadata = path.stat()
    except OSError:
        return None
    if not path.is_file():
        return None
    if not strong:
        return [metadata.st_size, metadata.st_mtime_ns]
    digest = hashlib.sha256()
    try:
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return {
        "size": metadata.st_size,
        "mtime_ns": metadata.st_mtime_ns,
        "sha256": digest.hexdigest(),
    }


def signature_matches(path: Path, signature: object) -> bool:
    if isinstance(signature, dict) and signature.get("sha256"):
        return file_signature(path, strong=True) == signature
    return file_signature(path) == signature
