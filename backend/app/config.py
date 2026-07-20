import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy.exc import OperationalError


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACE_DIR = (BASE_DIR / "workspace").resolve()
DEFAULT_EMBEDDING_MODEL_DIR = (BASE_DIR.parent / "models" / "Qwen3-VL-Embedding-2B").resolve()
DEFAULT_IMAGE_MODEL_PATH = (
    BASE_DIR.parent
    / "models"
    / "image_generation"
    / "juggernaut_xiii_ragnarok"
    / "checkpoint"
    / "juggernautXL_ragnarok.safetensors"
).resolve()
DEFAULT_IMAGE_CONFIG_DIR = (
    BASE_DIR.parent
    / "models"
    / "image_generation"
    / "juggernaut_xiii_ragnarok"
    / "diffusers_config"
).resolve()
DATABASE_PATH = DEFAULT_WORKSPACE_DIR / "app.db"

LANDSCAPE_TRANSITION_NAMES = (
    "fade",
    "dissolve",
    "fadeblack",
    "smoothleft",
    "smoothright",
)


class LandscapeTransitionEffect(BaseModel):
    name: Literal["fade", "dissolve", "fadeblack", "smoothleft", "smoothright"]
    enabled: bool = True
    percentage: int = Field(ge=0, le=100)


def default_landscape_transition_effects() -> list[LandscapeTransitionEffect]:
    return [
        LandscapeTransitionEffect(name="fade", percentage=45),
        LandscapeTransitionEffect(name="dissolve", percentage=25),
        LandscapeTransitionEffect(name="fadeblack", percentage=10),
        LandscapeTransitionEffect(name="smoothleft", percentage=10),
        LandscapeTransitionEffect(name="smoothright", percentage=10),
    ]


class Settings(BaseModel):
    app_host: str = "127.0.0.1"
    app_port: int = Field(default=18080, ge=1, le=65535)
    workspace_dir: Path = DEFAULT_WORKSPACE_DIR
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    landscape_transition_effects: list[LandscapeTransitionEffect] = Field(
        default_factory=default_landscape_transition_effects
    )
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    deepseek_max_tokens: int = Field(default=8192, ge=1, le=65536)
    deepseek_retry_count: int = Field(default=1, ge=0, le=10)
    pexels_api_key: str = ""
    pixabay_api_key: str = ""
    pexels_storage_dir: Path | None = None
    pixabay_storage_dir: Path | None = None
    media_search_cache_hours: int = Field(default=24, ge=24, le=168)
    media_search_download_limit: int = Field(default=3, ge=1, le=5)
    auto_fallback_enabled: bool = True
    auto_landscape_fallback_enabled: bool = False
    auto_fallback_review_required: bool = True
    auto_fallback_max_ratio_percent: int = Field(default=20, ge=0, le=100)
    auto_fallback_max_consecutive_shots: int = Field(default=2, ge=1, le=5)
    vision_embedding_model_dir: Path | None = (
        DEFAULT_EMBEDDING_MODEL_DIR if DEFAULT_EMBEDDING_MODEL_DIR.is_dir() else None
    )
    vision_embedding_device: str = "cuda:0"
    vision_embedding_dtype: str = "float16"
    vision_embedding_max_images: int = Field(default=4, ge=1, le=8)
    vision_embedding_max_pixels: int = Field(default=589824, ge=4096, le=1843200)
    vision_embedding_instruction: str = (
        "Retrieve documentary video shots relevant to the narration query."
    )
    image_generation_model_path: Path | None = (
        DEFAULT_IMAGE_MODEL_PATH if DEFAULT_IMAGE_MODEL_PATH.is_file() else None
    )
    image_generation_config_dir: Path | None = (
        DEFAULT_IMAGE_CONFIG_DIR if (DEFAULT_IMAGE_CONFIG_DIR / "model_index.json").is_file() else None
    )
    image_generation_python: Path | None = None
    image_generation_device: str = "cuda:0"
    image_generation_dtype: str = "float16"
    image_generation_width: int = Field(default=1344, ge=512, le=2048, multiple_of=64)
    image_generation_height: int = Field(default=768, ge=512, le=2048, multiple_of=64)
    image_generation_steps: int = Field(default=30, ge=1, le=100)
    image_generation_guidance_scale: float = Field(default=5.5, ge=0, le=30)
    image_generation_candidates_per_scene: int = Field(default=2, ge=1, le=4)
    image_generation_cpu_offload: bool = True
    image_generation_negative_prompt: str = (
        "text, watermark, logo, caption, signature, deformed anatomy, extra fingers, "
        "duplicate people, low resolution, blurry, oversaturated"
    )
    image_selection_semantic_weight: float = Field(default=0.7, ge=0, le=1)
    image_selection_technical_weight: float = Field(default=0.3, ge=0, le=1)
    image_selection_min_semantic_score: float = Field(default=0.2, ge=0, le=1)
    image_selection_min_total_score: float = Field(default=0.5, ge=0, le=1)
    image_selection_min_score_margin: float = Field(default=0.03, ge=0, le=1)
    image_selection_min_sharpness: float = Field(default=0.001, ge=0, le=1)
    image_selection_max_clipped_ratio: float = Field(default=0.55, ge=0, le=1)
    framepack_enabled: bool = False
    framepack_auto_start_worker: bool = False
    framepack_python: Path | None = None
    framepack_cache_dir: Path | None = None
    framepack_worker_host: str = "127.0.0.1"
    framepack_worker_port: int = Field(default=7861, ge=1, le=65535)
    framepack_model_id: str = "lllyasviel/FramePack_F1_I2V_HY_20250503"
    framepack_base_model_id: str = "hunyuanvideo-community/HunyuanVideo"
    framepack_sampling_type: str = "vanilla"
    framepack_allow_model_download: bool = False
    framepack_width: int = Field(default=832, ge=256, le=1920, multiple_of=16)
    framepack_height: int = Field(default=480, ge=256, le=1088, multiple_of=16)
    framepack_steps: int = Field(default=25, ge=1, le=100)
    framepack_guidance_scale: float = Field(default=9.0, ge=1, le=32)
    framepack_cpu_offload: bool = True
    framepack_max_ratio: float = Field(default=0.2, ge=0, le=1)
    framepack_max_retries: int = Field(default=1, ge=0, le=3)
    framepack_startup_timeout_seconds: float = Field(default=600, gt=0, le=3600)
    framepack_job_timeout_seconds: float = Field(default=3600, gt=0, le=14400)
    qwen_tts_root: Path | None = None
    qwen_tts_python: Path | None = None
    qwen_tts_model_dir: Path | None = None
    qwen_tts_device: str = "cuda:0"
    qwen_tts_dtype: str = "bfloat16"
    qwen_tts_language: str = "Chinese"
    qwen_tts_max_new_tokens: int = Field(default=2048, ge=128, le=16384)
    cosyvoice_root: Path | None = None
    cosyvoice_python: Path | None = None
    cosyvoice_model_dir: Path | None = None
    cosyvoice_fp16: bool = True
    cosyvoice_instruction: str = "You are a helpful assistant."
    cosyvoice_max_attempts: int = Field(default=3, ge=1, le=5)
    cosyvoice_min_chars_per_second: float = Field(default=2.8, gt=0, le=10)
    cosyvoice_duration_slack_seconds: float = Field(default=2.0, ge=0, le=10)
    cosyvoice_duration_outlier_ratio: float = Field(default=1.45, gt=1, le=3)

    @field_validator(
        "qwen_tts_root",
        "qwen_tts_python",
        "qwen_tts_model_dir",
        "cosyvoice_root",
        "cosyvoice_python",
        "cosyvoice_model_dir",
        "vision_embedding_model_dir",
        "image_generation_model_path",
        "image_generation_config_dir",
        "image_generation_python",
        "framepack_python",
        "framepack_cache_dir",
        "pexels_storage_dir",
        "pixabay_storage_dir",
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

    @field_validator("landscape_transition_effects")
    @classmethod
    def validate_landscape_transition_effects(cls, value):
        names = [item.name for item in value]
        if len(names) != len(set(names)) or set(names) != set(LANDSCAPE_TRANSITION_NAMES):
            raise ValueError("Landscape transition settings must contain each supported effect once")
        enabled = [item for item in value if item.enabled]
        if enabled and any(item.percentage <= 0 for item in enabled):
            raise ValueError("Enabled landscape transitions must have a positive percentage")
        if enabled and sum(item.percentage for item in enabled) != 100:
            raise ValueError("Enabled landscape transition percentages must total 100")
        by_name = {item.name: item for item in value}
        return [by_name[name] for name in LANDSCAPE_TRANSITION_NAMES]

    @field_validator("qwen_tts_device", "qwen_tts_language")
    @classmethod
    def non_empty_qwen_setting(cls, value):
        text = str(value or "").strip()
        if not text:
            raise ValueError("Qwen3-TTS device and language cannot be empty")
        return text

    @field_validator("vision_embedding_dtype")
    @classmethod
    def validate_vision_embedding_dtype(cls, value):
        dtype = str(value or "").strip().lower()
        if dtype not in {"bfloat16", "float16", "float32"}:
            raise ValueError("Unsupported vision embedding dtype")
        return dtype

    @field_validator("image_generation_dtype")
    @classmethod
    def validate_image_generation_dtype(cls, value):
        dtype = str(value or "").strip().lower()
        if dtype not in {"bfloat16", "float16", "float32"}:
            raise ValueError("Unsupported image generation dtype")
        return dtype

    @field_validator("image_generation_device", "image_generation_negative_prompt")
    @classmethod
    def non_empty_image_generation_setting(cls, value):
        text = str(value or "").strip()
        if not text:
            raise ValueError("Image generation device and negative prompt cannot be empty")
        return text

    @field_validator(
        "framepack_worker_host",
        "framepack_model_id",
        "framepack_base_model_id",
        "framepack_sampling_type",
    )
    @classmethod
    def non_empty_framepack_setting(cls, value):
        text = str(value or "").strip()
        if not text:
            raise ValueError("FramePack settings cannot be empty")
        return text

    @field_validator("vision_embedding_device", "vision_embedding_instruction")
    @classmethod
    def non_empty_vision_embedding_setting(cls, value):
        text = str(value or "").strip()
        if not text:
            raise ValueError("Vision embedding device and instruction cannot be empty")
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
        "cosyvoice_root",
        "cosyvoice_python",
        "cosyvoice_model_dir",
        "vision_embedding_model_dir",
        "image_generation_model_path",
        "image_generation_config_dir",
        "image_generation_python",
        "framepack_python",
        "framepack_cache_dir",
        "pexels_storage_dir",
        "pixabay_storage_dir",
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
