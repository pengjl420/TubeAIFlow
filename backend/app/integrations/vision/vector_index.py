import json
from pathlib import Path
from threading import Lock

from app.config import get_settings
from app.integrations.vision.embedding import MODEL_NAME, embed_text


INDEX_VERSION = 1
_INDEX_LOCK = Lock()


def upsert_shot(media_shot_id: str, text: str) -> int:
    with _INDEX_LOCK:
        path = _index_path()
        payload = _read_index(path)
        existing = next(
            (item for item in payload["vectors"].values() if item["media_shot_id"] == media_shot_id),
            None,
        )
        vector_id = int(existing["vector_id"]) if existing else int(payload["next_id"])
        if not existing:
            payload["next_id"] = vector_id + 1
        payload["vectors"][str(vector_id)] = {
            "vector_id": vector_id,
            "media_shot_id": media_shot_id,
            "model": MODEL_NAME,
            "vector": embed_text(text),
        }
        _write_index(path, payload)
    return vector_id


def search(query: str) -> dict[str, float]:
    query_vector = embed_text(query)
    if not any(query_vector):
        return {}
    with _INDEX_LOCK:
        payload = _read_index(_index_path())
    scores: dict[str, float] = {}
    for item in payload["vectors"].values():
        if item.get("model") != MODEL_NAME:
            continue
        score = sum(left * right for left, right in zip(query_vector, item["vector"]))
        scores[item["media_shot_id"]] = round(max(0.0, score), 6)
    return scores


def _index_path() -> Path:
    directory = get_settings().workspace_dir / "indexes"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "media_vectors.json"


def _read_index(path: Path) -> dict:
    if not path.exists():
        return {"version": INDEX_VERSION, "model": MODEL_NAME, "next_id": 1, "vectors": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": INDEX_VERSION, "model": MODEL_NAME, "next_id": 1, "vectors": {}}
    if not isinstance(payload.get("vectors"), dict):
        payload["vectors"] = {}
    payload.setdefault("next_id", 1)
    return payload


def _write_index(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
