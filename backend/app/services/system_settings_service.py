import json
from pathlib import Path

from sqlmodel import Session

from app.config import Settings, clear_settings_cache, get_settings
from app.models.system_setting import SystemSetting
from app.utils.time_utils import utc_now_iso


SECRET_FIELDS = {"deepseek_api_key"}


def get_public_settings() -> dict:
    settings = get_settings()
    data = settings.model_dump(mode="json")
    for field_name in SECRET_FIELDS:
        data[field_name] = ""
        data[f"{field_name}_configured"] = bool(getattr(settings, field_name))
    return data


def save_settings(session: Session, values: dict) -> dict:
    current = get_settings().model_dump(mode="json")
    for field_name in SECRET_FIELDS:
        value = str(values.pop(field_name, "") or "").strip()
        if value:
            current[field_name] = value
    current.update(values)
    settings = Settings.model_validate(current)
    _validate_paths(settings)

    record = session.get(SystemSetting, 1)
    serialized = json.dumps(settings.model_dump(mode="json"), ensure_ascii=False)
    if record:
        record.config_json = serialized
        record.updated_at = utc_now_iso()
    else:
        record = SystemSetting(id=1, config_json=serialized)
    session.add(record)
    session.commit()
    clear_settings_cache()
    return get_public_settings()


def clear_secret(session: Session, field_name: str) -> dict:
    if field_name not in SECRET_FIELDS:
        raise ValueError("Unknown secret setting")
    values = get_settings().model_dump(mode="json")
    values[field_name] = ""
    settings = Settings.model_validate(values)
    record = session.get(SystemSetting, 1)
    serialized = json.dumps(settings.model_dump(mode="json"), ensure_ascii=False)
    if record:
        record.config_json = serialized
        record.updated_at = utc_now_iso()
    else:
        record = SystemSetting(id=1, config_json=serialized)
    session.add(record)
    session.commit()
    clear_settings_cache()
    return get_public_settings()


def _validate_paths(settings: Settings) -> None:
    workspace = settings.workspace_dir.expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    if not workspace.is_dir():
        raise ValueError("Workspace path is not a directory")
    for field_name in ("index_tts_root", "index_tts_model_dir"):
        path: Path | None = getattr(settings, field_name)
        if path is not None and not path.is_dir():
            raise ValueError(f"{field_name} must be an existing directory")
    if settings.index_tts_python is not None and not settings.index_tts_python.is_file():
        raise ValueError("index_tts_python must be an existing file")
