import json
from pathlib import Path
from threading import Lock
from typing import Sequence

from app.config import get_settings
from app.integrations.vision.embedding import (
    MODEL_NAME,
    VECTOR_DIMENSIONS,
    embed_media,
    embed_text,
)


INDEX_VERSION = 1
INDEX_BASENAME = "media_vectors_qwen3_vl_2b"
_INDEX_LOCK = Lock()


def upsert_shot(
    media_shot_id: str,
    text: str,
    image_paths: Sequence[str | Path] = (),
) -> int:
    vector = _validated_vector(embed_media(text, image_paths))
    if not any(vector):
        raise RuntimeError("Cannot index an empty media shot")
    with _INDEX_LOCK:
        payload, index = _read_index()
        existing = next(
            (item for item in payload["vectors"].values() if item["media_shot_id"] == media_shot_id),
            None,
        )
        vector_id = int(existing["vector_id"]) if existing else int(payload["next_id"])
        if existing:
            index.remove_ids(_ids_array([vector_id]))
        else:
            payload["next_id"] = vector_id + 1
        index.add_with_ids(_vector_array([vector]), _ids_array([vector_id]))
        payload["vectors"][str(vector_id)] = {
            "vector_id": vector_id,
            "media_shot_id": media_shot_id,
            "model": MODEL_NAME,
        }
        _write_index(payload, index)
    return vector_id


def search(query: str) -> dict[str, float]:
    with _INDEX_LOCK:
        payload, index = _read_index()
    if not payload["vectors"] or index.ntotal == 0:
        return {}
    query_vector = _validated_vector(embed_text(query))
    if not any(query_vector):
        return {}
    count = min(index.ntotal, 1000)
    scores, vector_ids = index.search(_vector_array([query_vector]), count)
    results: dict[str, float] = {}
    for score, vector_id in zip(scores[0], vector_ids[0]):
        item = payload["vectors"].get(str(int(vector_id)))
        if item and item.get("model") == MODEL_NAME:
            results[item["media_shot_id"]] = round(max(0.0, float(score)), 6)
    return results


def remove_shot(media_shot_id: str) -> None:
    with _INDEX_LOCK:
        payload, index = _read_index()
        remove_ids = [
            int(vector_id)
            for vector_id, item in payload["vectors"].items()
            if item.get("media_shot_id") == media_shot_id
        ]
        if not remove_ids:
            return
        index.remove_ids(_ids_array(remove_ids))
        for vector_id in remove_ids:
            payload["vectors"].pop(str(vector_id), None)
        _write_index(payload, index)


def _index_directory() -> Path:
    directory = get_settings().workspace_dir / "indexes"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _read_index():
    metadata_path = _index_directory() / f"{INDEX_BASENAME}.json"
    index_path = _index_directory() / f"{INDEX_BASENAME}.faiss"
    empty_payload = {
        "version": INDEX_VERSION,
        "model": MODEL_NAME,
        "dimensions": VECTOR_DIMENSIONS,
        "next_id": 1,
        "vectors": {},
    }
    if not metadata_path.is_file() or not index_path.is_file():
        return empty_payload, _new_faiss_index()
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        if (
            payload.get("version") != INDEX_VERSION
            or payload.get("model") != MODEL_NAME
            or payload.get("dimensions") != VECTOR_DIMENSIONS
            or not isinstance(payload.get("vectors"), dict)
        ):
            return empty_payload, _new_faiss_index()
        index = _faiss().read_index(str(index_path))
        if index.d != VECTOR_DIMENSIONS:
            return empty_payload, _new_faiss_index()
        return payload, index
    except (OSError, ValueError, json.JSONDecodeError, RuntimeError):
        return empty_payload, _new_faiss_index()


def _write_index(payload: dict, index) -> None:
    directory = _index_directory()
    metadata_path = directory / f"{INDEX_BASENAME}.json"
    index_path = directory / f"{INDEX_BASENAME}.faiss"
    metadata_tmp = metadata_path.with_suffix(".json.tmp")
    index_tmp = index_path.with_suffix(".faiss.tmp")
    _faiss().write_index(index, str(index_tmp))
    metadata_tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    index_tmp.replace(index_path)
    metadata_tmp.replace(metadata_path)


def _new_faiss_index():
    faiss = _faiss()
    return faiss.IndexIDMap2(faiss.IndexFlatIP(VECTOR_DIMENSIONS))


def _vector_array(values):
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("numpy is required for the media vector index") from exc
    return np.asarray(values, dtype="float32")


def _validated_vector(vector):
    if len(vector) != VECTOR_DIMENSIONS:
        raise RuntimeError(
            f"Embedding dimension mismatch: expected {VECTOR_DIMENSIONS}, got {len(vector)}"
        )
    return vector


def _ids_array(values):
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("numpy is required for the media vector index") from exc
    return np.asarray(values, dtype="int64")


def _faiss():
    try:
        import faiss
    except ImportError as exc:
        raise RuntimeError("faiss-cpu is required for the media vector index") from exc
    return faiss
