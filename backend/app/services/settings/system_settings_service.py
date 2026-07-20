import json
from pathlib import Path

from sqlmodel import Session

from app.config import Settings, clear_settings_cache, get_settings
from app.models.settings import SystemSetting
from app.shared.time import utc_now_iso


SECRET_FIELDS = {"deepseek_api_key", "pexels_api_key", "pixabay_api_key"}


def get_public_settings() -> dict:
    settings = get_settings()
    data = settings.model_dump(mode="json")
    for field_name in SECRET_FIELDS:
        data[field_name] = ""
        data[f"{field_name}_configured"] = bool(getattr(settings, field_name))
    return data


def save_settings(session: Session, values: dict) -> dict:
    current = get_settings().model_dump(mode="json")
    changed_provider_secrets = []
    for field_name in SECRET_FIELDS:
        value = str(values.pop(field_name, "") or "").strip()
        if value:
            current[field_name] = value
            if field_name in {"pexels_api_key", "pixabay_api_key"}:
                changed_provider_secrets.append(field_name.removesuffix("_api_key"))
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
    if changed_provider_secrets:
        from app.services.media_library.media_provider_service import reset_provider_state

        for provider in changed_provider_secrets:
            reset_provider_state(session, provider)
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
    if field_name in {"pexels_api_key", "pixabay_api_key"}:
        from app.services.media_library.media_provider_service import reset_provider_state

        reset_provider_state(session, field_name.removesuffix("_api_key"))
    clear_settings_cache()
    return get_public_settings()


def get_ffmpeg_status() -> dict:
    from app.services.settings.ffmpeg_installer_service import get_ffmpeg_status as get_status

    return get_status()


def install_ffmpeg(session: Session) -> dict:
    from app.services.settings.ffmpeg_installer_service import install_ffmpeg as install

    return install(session)


def get_framepack_status() -> dict:
    from app.integrations.framepack.client import FramePackClient, FramePackUnavailableError
    from app.integrations.framepack.process_manager import worker_process_status

    settings = get_settings()
    result = {
        "enabled": settings.framepack_enabled,
        "configured": bool(settings.framepack_python),
        "worker": worker_process_status(),
        "health": None,
    }
    try:
        result["health"] = FramePackClient(settings).health(start_if_needed=False).model_dump()
    except FramePackUnavailableError as exc:
        result["health"] = {
            "status": "unavailable",
            "model_loaded": False,
            "error": str(exc),
        }
    return result


def _validate_paths(settings: Settings) -> None:
    workspace = settings.workspace_dir.expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    if not workspace.is_dir():
        raise ValueError("Workspace path is not a directory")
    for field_name in ("pexels_storage_dir", "pixabay_storage_dir"):
        path: Path | None = getattr(settings, field_name)
        if path is not None:
            path = path.expanduser().resolve()
            path.mkdir(parents=True, exist_ok=True)
            if not path.is_dir():
                raise ValueError(f"{field_name} must be a directory")
    for field_name in (
        "qwen_tts_root",
        "qwen_tts_model_dir",
        "chatterbox_root",
        "chatterbox_model_dir",
        "cosyvoice_root",
        "cosyvoice_model_dir",
        "vision_embedding_model_dir",
        "image_generation_config_dir",
        "framepack_cache_dir",
    ):
        path: Path | None = getattr(settings, field_name)
        if path is not None and not path.is_dir():
            raise ValueError(f"{field_name} must be an existing directory")
    if settings.qwen_tts_python is not None and not settings.qwen_tts_python.is_file():
        raise ValueError("qwen_tts_python must be an existing file")
    if settings.chatterbox_python is not None and not settings.chatterbox_python.is_file():
        raise ValueError("chatterbox_python must be an existing file")
    if settings.cosyvoice_python is not None and not settings.cosyvoice_python.is_file():
        raise ValueError("cosyvoice_python must be an existing file")
    if (
        settings.image_generation_model_path is not None
        and not settings.image_generation_model_path.is_file()
    ):
        raise ValueError("image_generation_model_path must be an existing file")
    if settings.image_generation_python is not None and not settings.image_generation_python.is_file():
        raise ValueError("image_generation_python must be an existing file")
    if settings.framepack_python is not None and not settings.framepack_python.is_file():
        raise ValueError("framepack_python must be an existing file")
