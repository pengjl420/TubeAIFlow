from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from pydantic import BaseModel

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
    def __init__(self, project_dir: Path):
        self.project_dir = project_dir.resolve()
        self.cache_path = self.project_dir / "work" / "artifact_cache.json"

    def write_json(self, relative_path: str, value: BaseModel | dict | list) -> Path:
        payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
        encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        return self._write(relative_path, encoded)

    def write_jsonl(self, relative_path: str, values: list[BaseModel]) -> Path:
        encoded = (
            "\n".join(json.dumps(value.model_dump(mode="json"), ensure_ascii=False) for value in values)
            + "\n"
        ).encode("utf-8")
        return self._write(relative_path, encoded)

    def write_bytes(self, relative_path: str, value: bytes) -> Path:
        return self._write(relative_path, value)

    def is_current(self, relative_path: str, input_hash: str) -> bool:
        path = self.project_dir / relative_path
        cache = self._read_cache()
        entry = cache.get(relative_path)
        return bool(
            path.is_file()
            and entry
            and entry.get("input_hash") == input_hash
            and entry.get("artifact_hash") == sha256_file(path)
        )

    def record_input_hash(self, relative_path: str, input_hash: str) -> None:
        path = self.project_dir / relative_path
        cache = self._read_cache()
        cache[relative_path] = {
            "input_hash": input_hash,
            "artifact_hash": sha256_file(path),
            "updated_at": utc_now_iso(),
        }
        self._write_cache(cache)

    def _write(self, relative_path: str, encoded: bytes) -> Path:
        path = (self.project_dir / relative_path).resolve()
        if self.project_dir not in path.parents:
            raise ValueError("Artifact path escapes project directory")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(encoded)
        temporary.replace(path)
        return path

    def _read_cache(self) -> dict[str, Any]:
        if not self.cache_path.is_file():
            return {}
        try:
            value = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _write_cache(self, value: dict[str, Any]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.cache_path)


class GenerationHistory:
    """Append-only provider generation history with one selected version per type."""

    def __init__(self, database_path: Path):
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(database_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS generations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                type TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt TEXT NOT NULL,
                input_json TEXT NOT NULL,
                output_json TEXT NOT NULL,
                version INTEGER NOT NULL,
                is_selected INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(project_id, type, version)
            )
            """
        )
        self.connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_generation_selected "
            "ON generations(project_id, type) WHERE is_selected = 1"
        )
        self.connection.commit()

    def append(
        self,
        *,
        project_id: str,
        generation_type: str,
        provider: str,
        model: str,
        prompt: str,
        input_data: dict,
        output_data: dict,
        selected: bool = True,
    ) -> int:
        with self.connection:
            version = int(
                self.connection.execute(
                    "SELECT COALESCE(MAX(version), 0) + 1 FROM generations WHERE project_id=? AND type=?",
                    (project_id, generation_type),
                ).fetchone()[0]
            )
            if selected:
                self.connection.execute(
                    "UPDATE generations SET is_selected=0 WHERE project_id=? AND type=?",
                    (project_id, generation_type),
                )
            self.connection.execute(
                """INSERT INTO generations
                (project_id,type,provider,model,prompt,input_json,output_json,version,is_selected,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    project_id,
                    generation_type,
                    provider,
                    model,
                    prompt,
                    json.dumps(input_data, ensure_ascii=False, sort_keys=True),
                    json.dumps(output_data, ensure_ascii=False, sort_keys=True),
                    version,
                    int(selected),
                    utc_now_iso(),
                ),
            )
        return version

    def versions(self, project_id: str, generation_type: str) -> list[dict]:
        rows = self.connection.execute(
            "SELECT * FROM generations WHERE project_id=? AND type=? ORDER BY version",
            (project_id, generation_type),
        ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        self.connection.close()
