import json
from pathlib import Path
import uuid

from sqlmodel import Session

from app.config import Settings, clear_settings_cache, get_settings
from app.infrastructure.credential_store import delete_secret, store_secret
from app.models.settings import SystemSetting
from app.shared.time import utc_now_iso


SECRET_FIELDS = {"deepseek_api_key"}
SECRET_SUFFIXES = ("_api_key", "_token", "_secret", "_password")


def get_public_settings() -> dict:
    settings = get_settings()
    data = settings.model_dump(mode="json")
    for field_name in SECRET_FIELDS:
        data[field_name] = ""
        data[f"{field_name}_configured"] = bool(getattr(settings, field_name))
    return data


def save_settings(session: Session, values: dict) -> dict:
    current = get_settings().model_dump(mode="json")
    record = session.get(SystemSetting, 1)
    credential_refs = _credential_refs(record)
    pending_secrets: dict[str, str] = {}
    for field_name in SECRET_FIELDS:
        value = str(values.pop(field_name, "") or "").strip()
        if value:
            current[field_name] = value
            pending_secrets[field_name] = value
    current.update(values)
    settings = Settings.model_validate(current)
    _validate_paths(settings)

    replaced_ids: list[str] = []
    created_ids: list[str] = []
    try:
        for field_name, value in pending_secrets.items():
            previous_id = credential_refs.get(field_name)
            credential_id = store_secret(
                f"settings-{field_name}-{uuid.uuid4().hex}", value
            )
            credential_refs[field_name] = credential_id
            created_ids.append(credential_id)
            if previous_id:
                replaced_ids.append(previous_id)
        serialized = _serialize_settings(settings, record, credential_refs)
        if record:
            record.config_json = serialized
            record.updated_at = utc_now_iso()
        else:
            record = SystemSetting(id=1, config_json=serialized)
        session.add(record)
        session.commit()
    except Exception:
        session.rollback()
        for credential_id in created_ids:
            delete_secret(credential_id)
        raise
    for credential_id in replaced_ids:
        delete_secret(credential_id)
    clear_settings_cache()
    return get_public_settings()


def clear_secret(session: Session, field_name: str) -> dict:
    if field_name not in SECRET_FIELDS:
        raise ValueError("Unknown secret setting")
    values = get_settings().model_dump(mode="json")
    values[field_name] = ""
    settings = Settings.model_validate(values)
    record = session.get(SystemSetting, 1)
    credential_refs = _credential_refs(record)
    credential_id = credential_refs.pop(field_name, None)
    serialized = _serialize_settings(settings, record, credential_refs)
    if record:
        record.config_json = serialized
        record.updated_at = utc_now_iso()
    else:
        record = SystemSetting(id=1, config_json=serialized)
    session.add(record)
    session.commit()
    if credential_id:
        delete_secret(credential_id)
    clear_settings_cache()
    return get_public_settings()


def get_ffmpeg_status() -> dict:
    from app.services.settings.ffmpeg_installer_service import get_ffmpeg_status as get_status

    return get_status()


def get_premiere_status() -> dict:
    from app.services.projects.prproj_export_service import get_premiere_status as get_status

    return get_status()


def install_ffmpeg(session: Session) -> dict:
    from app.services.settings.ffmpeg_installer_service import install_ffmpeg as install

    return install(session)


def _validate_paths(settings: Settings) -> None:
    workspace = settings.workspace_dir.expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    if not workspace.is_dir():
        raise ValueError("Workspace path is not a directory")
    for field_name in (
        "qwen_tts_root",
        "qwen_tts_model_dir",
        "cosyvoice_root",
        "cosyvoice_model_dir",
        "index_tts_root",
        "index_tts_model_dir",
        "moss_tts_root",
        "moss_tts_model_dir",
        "moss_tts_codec_dir",
        "image_generation_config_dir",
        "subtitle_whisper_model_path",
    ):
        path: Path | None = getattr(settings, field_name)
        if path is not None and not path.is_dir():
            raise ValueError(f"{field_name} must be an existing directory")
    if settings.premiere_pro_path is not None and not settings.premiere_pro_path.is_file():
        raise ValueError("premiere_pro_path must be an existing file")
    if settings.qwen_tts_python is not None and not settings.qwen_tts_python.is_file():
        raise ValueError("qwen_tts_python must be an existing file")
    if settings.cosyvoice_python is not None and not settings.cosyvoice_python.is_file():
        raise ValueError("cosyvoice_python must be an existing file")
    if settings.index_tts_python is not None and not settings.index_tts_python.is_file():
        raise ValueError("index_tts_python must be an existing file")
    if settings.moss_tts_python is not None and not settings.moss_tts_python.is_file():
        raise ValueError("moss_tts_python must be an existing file")
    if (
        settings.image_generation_model_path is not None
        and not settings.image_generation_model_path.is_file()
    ):
        raise ValueError("image_generation_model_path must be an existing file")
    if settings.image_generation_python is not None and not settings.image_generation_python.is_file():
        raise ValueError("image_generation_python must be an existing file")


def _serialize_settings(
    settings: Settings,
    record: SystemSetting | None,
    credential_refs: dict[str, str] | None = None,
) -> str:
    """Keep settings owned by optional/older modules during core setting updates."""
    data = settings.model_dump(mode="json")
    for field_name in SECRET_FIELDS:
        data.pop(field_name, None)
    if record:
        try:
            previous = json.loads(record.config_json)
        except (TypeError, json.JSONDecodeError):
            previous = {}
        if isinstance(previous, dict):
            for key, value in previous.items():
                if (
                    key not in Settings.model_fields
                    and key != "credential_refs"
                    and not _looks_secret(key)
                ):
                    data[key] = value
    refs = credential_refs if credential_refs is not None else _credential_refs(record)
    if refs:
        data["credential_refs"] = refs
    return json.dumps(data, ensure_ascii=False)


def migrate_plaintext_secrets(session: Session) -> int:
    """Move legacy plaintext settings into DPAPI before other services load them."""
    record = session.get(SystemSetting, 1)
    if not record:
        return 0
    try:
        data = json.loads(record.config_json)
    except (TypeError, json.JSONDecodeError):
        return 0
    if not isinstance(data, dict):
        return 0
    refs = _credential_refs(record)
    migrated = 0
    for field_name in SECRET_FIELDS:
        value = str(data.pop(field_name, "") or "").strip()
        if not value:
            continue
        refs[field_name] = store_secret(f"settings-{field_name}", value)
        migrated += 1
    if not migrated:
        return 0
    data["credential_refs"] = refs
    record.config_json = json.dumps(data, ensure_ascii=False)
    record.updated_at = utc_now_iso()
    session.add(record)
    session.commit()
    clear_settings_cache()
    return migrated


def _credential_refs(record: SystemSetting | None) -> dict[str, str]:
    if not record:
        return {}
    try:
        data = json.loads(record.config_json)
    except (TypeError, json.JSONDecodeError):
        return {}
    refs = data.get("credential_refs", {}) if isinstance(data, dict) else {}
    return {
        str(field_name): str(credential_id)
        for field_name, credential_id in refs.items()
        if isinstance(field_name, str) and isinstance(credential_id, str)
    } if isinstance(refs, dict) else {}


def _looks_secret(field_name: str) -> bool:
    return field_name.lower().endswith(SECRET_SUFFIXES)
