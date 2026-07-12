from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")


class Settings(BaseSettings):
    app_host: str = "127.0.0.1"
    app_port: int = 18080
    workspace_dir: Path = BASE_DIR / "workspace"
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    gemini_api_key: str = ""
    openai_api_key: str = ""
    deepl_api_key: str = ""
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    translation_timeout_seconds: float = 60.0
    translation_batch_size: int = 30
    translation_max_tokens: int = 8192
    translation_retry_count: int = 1
    index_tts_root: Path | None = None
    index_tts_python: Path | None = None
    index_tts_model_dir: Path | None = None
    index_tts_fp16: bool = True

    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.workspace_dir / 'app.db'}"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not settings.workspace_dir.is_absolute():
        settings.workspace_dir = (BASE_DIR / settings.workspace_dir).resolve()
    else:
        settings.workspace_dir = settings.workspace_dir.resolve()
    settings.workspace_dir.mkdir(parents=True, exist_ok=True)
    (settings.workspace_dir / "projects").mkdir(parents=True, exist_ok=True)
    (settings.workspace_dir / "voices").mkdir(parents=True, exist_ok=True)
    (settings.workspace_dir / "templates").mkdir(parents=True, exist_ok=True)
    return settings
