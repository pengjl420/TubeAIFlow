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
    qwen_tts_root: Path | None = None
    qwen_tts_python: Path | None = None
    qwen_tts_model_dir: Path | None = None
    qwen_tts_device: str = "cuda:0"
    qwen_tts_dtype: str = "bfloat16"
    qwen_tts_language: str = "Chinese"
    qwen_tts_max_new_tokens: int = Field(default=2048, ge=128, le=16384)
    chatterbox_root: Path | None = None
    chatterbox_python: Path | None = None
    chatterbox_model_dir: Path | None = None
    chatterbox_device: str = "cuda"
    chatterbox_language: str = "zh"
    chatterbox_t3_model: str = "v3"
    chatterbox_exaggeration: float = Field(default=0.5, ge=0, le=2)
    chatterbox_cfg_weight: float = Field(default=0.5, ge=0, le=1)
    chatterbox_temperature: float = Field(default=0.8, gt=0, le=5)
    cosyvoice_root: Path | None = None
    cosyvoice_python: Path | None = None
    cosyvoice_model_dir: Path | None = None
    cosyvoice_fp16: bool = True
    cosyvoice_speed: float = Field(default=1.0, ge=0.5, le=2)
    cosyvoice_instruction: str = "You are a helpful assistant."

    @field_validator(
        "qwen_tts_root",
        "qwen_tts_python",
        "qwen_tts_model_dir",
        "chatterbox_root",
        "chatterbox_python",
        "chatterbox_model_dir",
        "cosyvoice_root",
        "cosyvoice_python",
        "cosyvoice_model_dir",
        mode="before",
    )
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

    @field_validator("qwen_tts_dtype")
    @classmethod
    def validate_qwen_tts_dtype(cls, value):
        dtype = str(value or "").strip().lower()
        if dtype not in {"bfloat16", "float16", "float32"}:
            raise ValueError("Unsupported Qwen3-TTS dtype")
        return dtype

    @field_validator("qwen_tts_device", "qwen_tts_language")
    @classmethod
    def non_empty_qwen_setting(cls, value):
        text = str(value or "").strip()
        if not text:
            raise ValueError("Qwen3-TTS device and language cannot be empty")
        return text

    @field_validator("chatterbox_t3_model")
    @classmethod
    def validate_chatterbox_model(cls, value):
        model = str(value or "").strip().lower()
        if model not in {"v2", "v3"}:
            raise ValueError("Unsupported Chatterbox multilingual model")
        return model

    @field_validator("chatterbox_device", "chatterbox_language")
    @classmethod
    def non_empty_chatterbox_setting(cls, value):
        text = str(value or "").strip()
        if not text:
            raise ValueError("Chatterbox device and language cannot be empty")
        return text

    @property
    def database_url(self) -> str:
        return f"sqlite:///{DATABASE_PATH}"


def _normalize_paths(settings: Settings) -> Settings:
    workspace = settings.workspace_dir.expanduser()
    settings.workspace_dir = (BASE_DIR / workspace).resolve() if not workspace.is_absolute() else workspace.resolve()
    for field_name in (
        "qwen_tts_root",
        "qwen_tts_python",
        "qwen_tts_model_dir",
        "chatterbox_root",
        "chatterbox_python",
        "chatterbox_model_dir",
        "cosyvoice_root",
        "cosyvoice_python",
        "cosyvoice_model_dir",
    ):
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
        from app.models.settings import SystemSetting

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
