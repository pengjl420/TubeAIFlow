from __future__ import annotations

import hashlib
import json
from typing import Any


def dump_json(value: Any, *, pretty: bool = False, sort_keys: bool = False) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=2 if pretty else None,
        sort_keys=sort_keys,
        separators=None,
    )


def load_json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        loaded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def stable_json_hash(value: Any) -> str:
    encoded = dump_json(value, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
