import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Callable

import httpx
from sqlmodel import Session, select

from app.config import get_settings
from app.models.project import Project
from app.models.segment import Segment
from app.utils.project_paths import ensure_project_dirs, get_output_stem, get_project_work_dir


logger = logging.getLogger(__name__)


def save_empty_translation(session: Session, project: Project) -> Path:
    segments = session.exec(
        select(Segment)
        .where(Segment.project_id == project.id)
        .order_by(Segment.segment_index)
    ).all()
    data = [
        {
            "segment_id": segment.segment_id,
            "text_zh": segment.text_zh,
            "text_en": segment.text_en or "",
        }
        for segment in segments
    ]
    base_dir = get_project_work_dir(project, get_settings().workspace_dir)
    ensure_project_dirs(base_dir)
    translation_dir = base_dir / "translation"
    translation_dir.mkdir(parents=True, exist_ok=True)
    output_path = translation_dir / f"{get_output_stem(project)}_translation.json"
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def translate_project_to_english(session: Session, project: Project, overwrite: bool = False) -> Path:
    segments = session.exec(
        select(Segment)
        .where(Segment.project_id == project.id)
        .order_by(Segment.segment_index)
    ).all()
    if not segments:
        raise ValueError("Project has no segments to translate")

    missing_segments = [
        segment
        for segment in segments
        if overwrite or not (segment.text_en or "").strip()
    ]
    if missing_segments:
        settings = get_settings()
        if not settings.deepseek_api_key:
            raise ValueError("DeepSeek API Key is not configured in System Settings")

        project.status = "translating"
        project.updated_at = datetime.utcnow().isoformat()
        session.add(project)
        session.commit()

        translations = _translate_segments_with_deepseek(missing_segments, _get_translation_log_path(project))
        for segment in missing_segments:
            translated = translations.get(segment.segment_id, "").strip()
            if not translated:
                raise RuntimeError(f"DeepSeek returned no translation for segment {segment.segment_id}")
            segment.text_en = translated
            segment.updated_at = datetime.utcnow().isoformat()
            session.add(segment)
        session.commit()

    path = save_translation(session, project)
    project.updated_at = datetime.utcnow().isoformat()
    session.add(project)
    session.commit()
    return path


def save_translation(session: Session, project: Project) -> Path:
    segments = session.exec(
        select(Segment)
        .where(Segment.project_id == project.id)
        .order_by(Segment.segment_index)
    ).all()
    data = [
        {
            "segment_id": segment.segment_id,
            "text_zh": segment.text_zh,
            "text_en": segment.text_en or "",
        }
        for segment in segments
    ]
    output_path = get_translation_path(project)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def load_translation(project: Project) -> dict[str, str]:
    path = get_translation_path(project)
    if not path.exists():
        raise ValueError("translation.json does not exist")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("translation.json is not valid JSON") from exc
    if not isinstance(data, list):
        raise ValueError("translation.json must contain a list")
    translations: dict[str, str] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        segment_id = str(item.get("segment_id") or "").strip()
        text_en = str(item.get("text_en") or "").strip()
        if segment_id and text_en:
            translations[segment_id] = text_en
    return translations


def get_translation_path(project: Project) -> Path:
    base_dir = get_project_work_dir(project, get_settings().workspace_dir)
    ensure_project_dirs(base_dir)
    return base_dir / "translation" / f"{get_output_stem(project)}_translation.json"


def translate_subtitle_cues_to_english(project: Project, zh_cues: list[dict]) -> tuple[Path, dict[str, str]]:
    if not zh_cues:
        raise ValueError("No Chinese subtitle cues to translate")

    settings = get_settings()
    if not settings.deepseek_api_key:
        raise ValueError("DeepSeek API Key is not configured in System Settings")

    translations = _translate_cues_with_deepseek(zh_cues, _get_translation_log_path(project))
    missing = [
        str(cue.get("cue_id") or "").strip()
        for cue in zh_cues
        if not translations.get(str(cue.get("cue_id") or "").strip(), "").strip()
    ]
    if missing:
        raise RuntimeError(f"DeepSeek returned no translation for subtitle cue {missing[0]}")

    data = [
        {
            "cue_id": cue["cue_id"],
            "segment_id": cue.get("segment_id"),
            "start": cue["start"],
            "end": cue["end"],
            "text_zh": cue["text_zh"],
            "text_en": translations[cue["cue_id"]],
        }
        for cue in zh_cues
    ]
    output_path = get_translation_path(project)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path, translations


def load_cue_translation(project: Project) -> dict[str, str]:
    path = get_translation_path(project)
    if not path.exists():
        raise ValueError("translation.json does not exist")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("translation.json is not valid JSON") from exc
    if not isinstance(data, list):
        raise ValueError("translation.json must contain a list")
    translations: dict[str, str] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        cue_id = str(item.get("cue_id") or "").strip()
        text_en = str(item.get("text_en") or "").strip()
        if cue_id and text_en:
            translations[cue_id] = text_en
    return translations


def _translate_segments_with_deepseek(
    segments: list[Segment],
    log_path: Path | None = None,
) -> dict[str, str]:
    settings = get_settings()
    batch_size = max(1, settings.translation_batch_size)
    translations: dict[str, str] = {}
    for batch_index, start in enumerate(range(0, len(segments), batch_size), start=1):
        batch = segments[start:start + batch_size]
        translations.update(_translate_segment_batch(batch, batch_index, log_path))
    return translations


def _translate_segment_batch(
    segments: list[Segment],
    batch_index: int,
    log_path: Path | None,
) -> dict[str, str]:
    settings = get_settings()
    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You translate Chinese subtitles into natural English. "
                    "Keep the original segment_id values exactly. "
                    "Do not merge, split, summarize, add explanations, or change the order. "
                    'Return only valid JSON with this exact top-level shape: {"translations": [...]}.'
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "segments": [
                            {
                                "segment_id": segment.segment_id,
                                "text_zh": segment.text_zh,
                            }
                            for segment in segments
                        ],
                        "output_schema": {
                            "translations": [
                                {
                                    "segment_id": "0001",
                                    "text_en": "English subtitle text",
                                }
                            ]
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
        "max_tokens": max(1, settings.translation_max_tokens),
    }
    return _request_deepseek_json(
        payload,
        "translation",
        batch_index,
        len(segments),
        log_path,
        lambda data: _parse_complete_translation_batch(
            data,
            _parse_translation_response,
            [segment.segment_id for segment in segments],
            "segment",
        ),
    )


def _translate_cues_with_deepseek(
    zh_cues: list[dict],
    log_path: Path | None = None,
) -> dict[str, str]:
    settings = get_settings()
    batch_size = max(1, settings.translation_batch_size)
    translations: dict[str, str] = {}
    for batch_index, start in enumerate(range(0, len(zh_cues), batch_size), start=1):
        batch = zh_cues[start:start + batch_size]
        translations.update(_translate_cue_batch(batch, batch_index, log_path))
    return translations


def _translate_cue_batch(
    zh_cues: list[dict],
    batch_index: int,
    log_path: Path | None,
) -> dict[str, str]:
    settings = get_settings()
    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You translate Chinese subtitle cues into natural English. "
                    "Keep the original cue_id values exactly. "
                    "Each output item must correspond to exactly one input cue. "
                    "Do not merge, split, summarize, add explanations, or change the order. "
                    'Return only valid JSON with this exact top-level shape: {"translations": [...]}.'
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "cues": [
                            {
                                "cue_id": cue["cue_id"],
                                "text_zh": cue["text_zh"],
                            }
                            for cue in zh_cues
                        ],
                        "output_schema": {
                            "translations": [
                                {
                                    "cue_id": "0001",
                                    "text_en": "English subtitle text",
                                }
                            ]
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
        "max_tokens": max(1, settings.translation_max_tokens),
    }
    try:
        return _request_deepseek_json(
            payload,
            "subtitle translation",
            batch_index,
            len(zh_cues),
            log_path,
            lambda data: _parse_complete_translation_batch(
                data,
                _parse_cue_translation_response,
                [str(cue["cue_id"]) for cue in zh_cues],
                "subtitle cue",
            ),
        )
    except RuntimeError:
        if len(zh_cues) <= 1:
            raise
        midpoint = len(zh_cues) // 2
        _append_translation_log(
            log_path,
            {
                "event": "deepseek_batch_split",
                "operation": "subtitle translation",
                "batch": batch_index,
                "items": len(zh_cues),
                "left_items": midpoint,
                "right_items": len(zh_cues) - midpoint,
            },
        )
        translations = _translate_cue_batch(zh_cues[:midpoint], batch_index, log_path)
        translations.update(_translate_cue_batch(zh_cues[midpoint:], batch_index, log_path))
        return translations


def _parse_complete_translation_batch(
    data: object,
    response_parser: Callable[[object], dict[str, str]],
    expected_ids: list[str],
    item_name: str,
) -> dict[str, str]:
    translations = response_parser(data)
    missing = [item_id for item_id in expected_ids if not translations.get(item_id, "").strip()]
    if missing:
        raise RuntimeError(
            f"DeepSeek omitted {len(missing)} {item_name} translation(s); first missing id: {missing[0]}"
        )
    return translations


def _request_deepseek_json(
    payload: dict,
    operation: str,
    batch_index: int,
    item_count: int,
    log_path: Path | None,
    response_parser: Callable[[object], dict[str, str]],
) -> dict[str, str]:
    settings = get_settings()
    url = settings.deepseek_base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }
    attempts = max(1, settings.translation_retry_count + 1)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        request_payload = _payload_for_attempt(payload, attempt)
        try:
            response = httpx.post(
                url,
                headers=headers,
                json=request_payload,
                timeout=settings.translation_timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
            choice = body["choices"][0]
            finish_reason = str(choice.get("finish_reason") or "unknown")
            content = choice["message"]["content"]
            parsed = _parse_deepseek_json_content(content)
            _write_translation_diagnostic(
                log_path,
                operation,
                batch_index,
                item_count,
                attempt,
                body,
                content,
                parsed,
            )
            if finish_reason != "stop":
                raise RuntimeError(f"DeepSeek stopped with finish_reason={finish_reason}")
            return response_parser(parsed)
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
            last_error = exc
            _write_translation_error(log_path, operation, batch_index, item_count, attempt, exc)
            if attempt < attempts:
                continue

    if isinstance(last_error, httpx.HTTPError):
        raise RuntimeError(f"DeepSeek {operation} request failed after {attempts} attempt(s): {last_error}") from last_error
    raise RuntimeError(f"DeepSeek {operation} response failed after {attempts} attempt(s): {last_error}") from last_error


def _payload_for_attempt(payload: dict, attempt: int) -> dict:
    if attempt == 1:
        return payload
    messages = [dict(message) for message in payload["messages"]]
    messages[0]["content"] = (
        str(messages[0]["content"])
        + " Previous output could not be parsed. The top-level translations value must be a JSON array, "
        "and every item must contain the unchanged input id plus a non-empty text_en string."
    )
    return {**payload, "messages": messages, "temperature": 0}


def _get_translation_log_path(project: Project) -> Path:
    base_dir = get_project_work_dir(project, get_settings().workspace_dir)
    ensure_project_dirs(base_dir)
    return base_dir / "logs" / "app.log"


def _write_translation_diagnostic(
    log_path: Path | None,
    operation: str,
    batch_index: int,
    item_count: int,
    attempt: int,
    body: dict,
    content: object,
    parsed: object,
) -> None:
    choice = body.get("choices", [{}])[0] if isinstance(body.get("choices"), list) else {}
    data = {
        "event": "deepseek_response",
        "operation": operation,
        "batch": batch_index,
        "items": item_count,
        "attempt": attempt,
        "request_id": str(body.get("id") or ""),
        "model": str(body.get("model") or ""),
        "finish_reason": str(choice.get("finish_reason") or "unknown") if isinstance(choice, dict) else "unknown",
        "usage": body.get("usage") if isinstance(body.get("usage"), dict) else {},
        "content_chars": len(content) if isinstance(content, str) else None,
        "response_shape": _describe_response_shape(parsed),
    }
    _append_translation_log(log_path, data)


def _write_translation_error(
    log_path: Path | None,
    operation: str,
    batch_index: int,
    item_count: int,
    attempt: int,
    exc: Exception,
) -> None:
    data = {
        "event": "deepseek_error",
        "operation": operation,
        "batch": batch_index,
        "items": item_count,
        "attempt": attempt,
        "error_type": type(exc).__name__,
        "error": str(exc)[:500],
    }
    logger.warning("DeepSeek %s batch %s attempt %s failed: %s", operation, batch_index, attempt, exc)
    _append_translation_log(log_path, data)


def _append_translation_log(log_path: Path | None, data: dict) -> None:
    if log_path is None:
        return
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {"time": datetime.utcnow().isoformat(), **data}
        with log_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        # Diagnostic logging must not turn a successful translation into a failed request.
        logger.warning("Could not write translation diagnostic log %s: %s", log_path, exc)


def _parse_deepseek_json_content(content: object) -> dict | list:
    if isinstance(content, (dict, list)):
        return content
    if not isinstance(content, str):
        raise TypeError("DeepSeek message content must be a JSON string")

    text = content.strip()
    if not text:
        raise json.JSONDecodeError("Empty DeepSeek message content", content, 0)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = json.loads(_extract_json_object(text))
    if not isinstance(parsed, (dict, list)):
        raise TypeError("DeepSeek JSON response must be an object or list")
    return parsed


def _extract_json_object(text: str) -> str:
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()

    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            _, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        return text[index:index + end]
    raise json.JSONDecodeError("No JSON object found in DeepSeek message content", text, 0)


def _parse_cue_translation_response(data: object) -> dict[str, str]:
    items = _get_translation_items(data)
    if not isinstance(items, list):
        raise RuntimeError(
            "DeepSeek subtitle translation response must contain a translations list "
            f"or id-to-text mapping; got {_describe_response_shape(data)}"
        )
    translations: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        cue_id = str(item.get("cue_id") or item.get("id") or "").strip()
        text_en = _get_translation_text(item)
        if cue_id and text_en:
            translations[cue_id] = text_en
    if not translations:
        raise RuntimeError("DeepSeek subtitle translation response contains no usable translations")
    return translations


def _parse_translation_response(data: object) -> dict[str, str]:
    items = _get_translation_items(data)
    if not isinstance(items, list):
        raise RuntimeError(
            "DeepSeek translation response must contain a translations list "
            f"or id-to-text mapping; got {_describe_response_shape(data)}"
        )
    translations: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        segment_id = str(item.get("segment_id") or item.get("id") or "").strip()
        text_en = _get_translation_text(item)
        if segment_id and text_en:
            translations[segment_id] = text_en
    if not translations:
        raise RuntimeError("DeepSeek translation response contains no usable translations")
    return translations


def _get_translation_items(data: object) -> object:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return None

    if _looks_like_translation_item(data):
        return [data]

    mapped_items = _mapping_to_translation_items(data)
    if mapped_items:
        return mapped_items

    for key in (
        "translations",
        "translation",
        "items",
        "results",
        "subtitles",
        "translated_subtitles",
        "subtitle_translations",
        "translated_cues",
        "cues",
        "segments",
    ):
        value = data.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            if _looks_like_translation_item(value):
                return [value]
            mapped_items = _mapping_to_translation_items(value)
            if mapped_items:
                return mapped_items
            nested = _get_translation_items(value)
            if isinstance(nested, list):
                return nested

    for key in ("data", "result", "output"):
        value = data.get(key)
        nested = _get_translation_items(value)
        if isinstance(nested, list):
            return nested
    return None


def _mapping_to_translation_items(data: dict) -> list[dict]:
    items: list[dict] = []
    for key, value in data.items():
        raw_id = str(key or "").strip()
        id_match = re.fullmatch(r"(?:(?:cue|segment)[_-]?)?(\d+)", raw_id, flags=re.IGNORECASE)
        if not id_match:
            continue
        item_id = id_match.group(1)
        if isinstance(value, str):
            text_en = value.strip()
        elif isinstance(value, dict):
            text_en = _get_translation_text(value)
        else:
            text_en = ""
        if item_id and text_en:
            items.append({"id": item_id, "text_en": text_en})
    return items


def _looks_like_translation_item(data: dict) -> bool:
    has_id = any(str(data.get(key) or "").strip() for key in ("cue_id", "segment_id", "id"))
    return has_id and bool(_get_translation_text(data))


def _get_translation_text(item: dict) -> str:
    for key in ("text_en", "english", "translation", "translated_text", "text"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return ""


def _describe_response_shape(data: object) -> str:
    if isinstance(data, list):
        return f"list(len={len(data)})"
    if isinstance(data, dict):
        keys = ", ".join(str(key) for key in list(data.keys())[:8])
        return f"object(keys=[{keys}])"
    return type(data).__name__
