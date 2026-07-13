import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy.exc import OperationalError


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACE_DIR = (BASE_DIR / "workspace").resolve()
DATABASE_PATH = DEFAULT_WORKSPACE_DIR / "app.db"


class Settings(BaseModel):
    app_host: str = "127.0.0.1"
    app_port: int = Field(default=18080, ge=1, le=65535)
    workspace_dir: Path = DEFAULT_WORKSPACE_DIR
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    translation_timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    translation_batch_size: int = Field(default=30, ge=1, le=200)
    translation_max_tokens: int = Field(default=8192, ge=1, le=65536)
    translation_retry_count: int = Field(default=1, ge=0, le=10)
    index_tts_root: Path | None = None
    index_tts_python: Path | None = None
    index_tts_model_dir: Path | None = None
    index_tts_fp16: bool = True

    @field_validator("index_tts_root", "index_tts_python", "index_tts_model_dir", mode="before")
    @classmethod
    def empty_path_is_none(cls, value):
        return None if value is None or str(value).strip() == "" else value

    @field_validator("deepseek_model", mode="before")
    @classmethod
    def validate_deepseek_model(cls, value):
        model = str(value or "").strip()
        if model in {"deepseek-chat", "deepseek-reasoner", ""}:
            return "deepseek-v4-flash"
        if model not in {"deepseek-v4-flash", "deepseek-v4-pro"}:
            raise ValueError("Unsupported DeepSeek model")
        return model

    @property
    def database_url(self) -> str:
        return f"sqlite:///{DATABASE_PATH}"


def _normalize_paths(settings: Settings) -> Settings:
    workspace = settings.workspace_dir.expanduser()
    settings.workspace_dir = (BASE_DIR / workspace).resolve() if not workspace.is_absolute() else workspace.resolve()
    for field_name in ("index_tts_root", "index_tts_python", "index_tts_model_dir"):
        value = getattr(settings, field_name)
        if value is not None:
            setattr(settings, field_name, value.expanduser().resolve())
    return settings


def _ensure_workspace(settings: Settings) -> None:
    settings.workspace_dir.mkdir(parents=True, exist_ok=True)
    for name in ("projects", "voices", "templates"):
        (settings.workspace_dir / name).mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    try:
        from sqlmodel import Session

        from app.database import engine
        from app.models.system_setting import SystemSetting

        with Session(engine) as session:
            record = session.get(SystemSetting, 1)
            if record:
                data = json.loads(record.config_json)
                if isinstance(data, dict):
                    settings = Settings.model_validate(data)
    except (ImportError, json.JSONDecodeError, OperationalError, ValidationError):
        # Defaults allow database initialization before the settings table exists.
        settings = Settings()
    settings = _normalize_paths(settings)
    _ensure_workspace(settings)
    return settings


def clear_settings_cache() -> None:
    get_settings.cache_clear()
