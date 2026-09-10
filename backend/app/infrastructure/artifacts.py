from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.infrastructure.atomic_files import write_bytes_atomic, write_json_atomic
from app.shared.time import utc_now_iso


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ArtifactStore:
    """Project-scoped, path-safe artifact writer with verified input signatures."""

    def __init__(self, project_dir: Path, cache_relative_path: str = "work/artifact_cache.json"):
        self.project_dir = project_dir.resolve()
        self.cache_path = self._resolve(cache_relative_path)

    def write_json(self, relative_path: str, value: BaseModel | dict | list) -> Path:
        payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
        path = self._resolve(relative_path)
        write_json_atomic(path, payload)
        return path

    def write_jsonl(self, relative_path: str, values: list[BaseModel]) -> Path:
        encoded = (
            "\n".join(
                json.dumps(value.model_dump(mode="json"), ensure_ascii=False) for value in values
            )
            + "\n"
        ).encode("utf-8")
        return self.write_bytes(relative_path, encoded)

    def write_bytes(self, relative_path: str, value: bytes) -> Path:
        path = self._resolve(relative_path)
        write_bytes_atomic(path, value)
        return path

    def is_current(self, relative_path: str, input_hash: str) -> bool:
        path = self._resolve(relative_path)
        entry = self._read_cache().get(relative_path)
        return bool(
            path.is_file()
            and entry
            and entry.get("input_hash") == input_hash
            and entry.get("artifact_hash") == sha256_file(path)
        )

    def record_input_hash(self, relative_path: str, input_hash: str) -> None:
        path = self._resolve(relative_path)
        if not path.is_file():
            raise FileNotFoundError(path)
        cache = self._read_cache()
        cache[relative_path] = {
            "input_hash": input_hash,
            "artifact_hash": sha256_file(path),
            "updated_at": utc_now_iso(),
        }
        write_json_atomic(self.cache_path, cache)

    def _resolve(self, relative_path: str) -> Path:
        candidate = Path(relative_path)
        if candidate.is_absolute():
            raise ValueError("Artifact path must be project-relative")
        path = (self.project_dir / candidate).resolve()
        if path == self.project_dir or self.project_dir not in path.parents:
            raise ValueError("Artifact path escapes project directory")
        return path

    def _read_cache(self) -> dict[str, Any]:
        if not self.cache_path.is_file():
            return {}
        try:
            value = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}
