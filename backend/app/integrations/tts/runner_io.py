import json
import os
import time
import uuid
from pathlib import Path


def write_json(path: Path, data, *, replace_attempts: int = 12) -> None:
    """Atomically write JSON, tolerating transient Windows reader locks."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        for attempt in range(replace_attempts):
            try:
                os.replace(temp_path, path)
                return
            except PermissionError:
                if attempt + 1 >= replace_attempts:
                    raise
                time.sleep(min(0.02 * (2**attempt), 0.25))
    finally:
        temp_path.unlink(missing_ok=True)
