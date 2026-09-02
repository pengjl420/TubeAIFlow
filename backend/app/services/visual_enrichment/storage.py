from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.infrastructure.artifacts import (
    ArtifactStore as ArtifactStore,
    sha256_bytes as sha256_bytes,
    sha256_file as sha256_file,
)
from app.shared.time import utc_now_iso


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
