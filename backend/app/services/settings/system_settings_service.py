import json
from pathlib import Path

from sqlmodel import Session

from app.config import Settings, clear_settings_cache, get_settings
from app.models.settings import SystemSetting
from app.shared.time import utc_now_iso


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
    serialized = _serialize_settings(settings, record)
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
    serialized = _serialize_settings(settings, record)
    if record:
        record.config_json = serialized
        record.updated_at = utc_now_iso()
    else:
        record = SystemSetting(id=1, config_json=serialized)
    session.add(record)
    session.commit()
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


def _serialize_settings(settings: Settings, record: SystemSetting | None) -> str:
    """Keep settings owned by optional/older modules during core setting updates."""
    data = settings.model_dump(mode="json")
    if record:
        try:
            previous = json.loads(record.config_json)
        except (TypeError, json.JSONDecodeError):
            previous = {}
        if isinstance(previous, dict):
            for key, value in previous.items():
                if key not in Settings.model_fields:
                    data[key] = value
    return json.dumps(data, ensure_ascii=False)
