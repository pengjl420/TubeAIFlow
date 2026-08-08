import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from sqlalchemy.exc import OperationalError


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACE_DIR = (BASE_DIR / "workspace").resolve()
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

STORYBOARD_TRANSITION_NAMES = (
    "fade",
    "dissolve",
    "fadeblack",
    "smoothleft",
    "smoothright",
)


class StoryboardTransitionEffect(BaseModel):
    name: Literal["fade", "dissolve", "fadeblack", "smoothleft", "smoothright"]
    enabled: bool = True
    percentage: int = Field(ge=0, le=100)


def default_storyboard_transition_effects() -> list[StoryboardTransitionEffect]:
    return [
        StoryboardTransitionEffect(name="fade", percentage=45),
        StoryboardTransitionEffect(name="dissolve", percentage=25),
        StoryboardTransitionEffect(name="fadeblack", percentage=10),
        StoryboardTransitionEffect(name="smoothleft", percentage=10),
        StoryboardTransitionEffect(name="smoothright", percentage=10),
    ]


# Kept as an import-compatible alias for extensions written against older builds.
LandscapeTransitionEffect = StoryboardTransitionEffect


class Settings(BaseModel):
    app_host: str = "127.0.0.1"
    app_port: int = Field(default=18080, ge=1, le=65535)
    workspace_dir: Path = DEFAULT_WORKSPACE_DIR
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    duix_base_url: str = "http://127.0.0.1:8383"
    duix_host_shared_dir: Path = Path(r"D:\duix_avatar_data\face2face")
    duix_container_shared_dir: str = "/code/data"
    duix_poll_interval_seconds: float = Field(default=3.0, ge=0.5, le=30)
    duix_task_timeout_seconds: float = Field(default=43200, ge=60, le=86400)
    premiere_pro_path: Path | None = None
    storyboard_transition_effects: list[StoryboardTransitionEffect] = Field(
        default_factory=default_storyboard_transition_effects
    )
    storyboard_transition_group_min_clips: int = Field(default=2, ge=2, le=20)
    storyboard_transition_group_max_clips: int = Field(default=5, ge=2, le=20)
    storyboard_transition_min_per_group: int = Field(default=1, ge=0, le=10)
    storyboard_transition_max_per_group: int = Field(default=2, ge=0, le=10)
    storyboard_transition_duration_seconds: float = Field(default=0.45, ge=0.2, le=2.0)
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    deepseek_max_tokens: int = Field(default=8192, ge=1, le=65536)
    deepseek_retry_count: int = Field(default=1, ge=0, le=10)
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
    cosyvoice_max_attempts: int = Field(default=5, ge=1, le=5)
    cosyvoice_min_chars_per_second: float = Field(default=2.8, gt=0, le=10)
    cosyvoice_duration_slack_seconds: float = Field(default=3.0, ge=0, le=10)
    cosyvoice_duration_outlier_ratio: float = Field(default=1.45, gt=1, le=3)
    index_tts_root: Path | None = Path(r"D:\index-tts")
    index_tts_python: Path | None = Path(r"D:\index-tts\python310\python.exe")
    index_tts_model_dir: Path | None = Path(r"D:\index-tts\checkpoints")
    index_tts_device: str = "cuda:0"
    index_tts_max_text_tokens_per_sentence: int = Field(default=120, ge=20, le=400)
    moss_tts_root: Path | None = Path(r"D:\MOSS-TTS")
    moss_tts_python: Path | None = Path(r"D:\MOSS-TTS\.venv\Scripts\python.exe")
    moss_tts_model_dir: Path | None = Path(r"D:\MOSS-TTS\models\MOSS-TTS-Local-Transformer-v1.5")
    moss_tts_codec_dir: Path | None = Path(
        r"D:\MOSS-TTS\models\cache\hub\models--OpenMOSS-Team--MOSS-Audio-Tokenizer-v2"
        r"\snapshots\f6e20e543b33d2c252a7ef71bdf8aa71e5ff9169"
    )
    moss_tts_device: str = "cuda:0"
    moss_tts_dtype: str = "bfloat16"
    moss_tts_max_new_tokens: int = Field(default=7500, ge=128, le=12000)
    subtitle_max_display_units: int = Field(default=22, ge=8, le=80)
    subtitle_min_cue_duration_ms: int = Field(default=1000, ge=300, le=5000)
    subtitle_max_cue_duration_ms: int = Field(default=6000, ge=1000, le=15000)
    subtitle_target_characters_per_second: float = Field(default=7.0, ge=1, le=20)

    @field_validator(
        "qwen_tts_root",
        "qwen_tts_python",
        "qwen_tts_model_dir",
        "cosyvoice_root",
        "cosyvoice_python",
        "cosyvoice_model_dir",
        "index_tts_root",
        "index_tts_python",
        "index_tts_model_dir",
        "moss_tts_root",
        "moss_tts_python",
        "moss_tts_model_dir",
        "moss_tts_codec_dir",
        "image_generation_model_path",
        "image_generation_config_dir",
        "image_generation_python",
        "premiere_pro_path",
        "duix_host_shared_dir",
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

    @field_validator("moss_tts_dtype")
    @classmethod
    def validate_moss_tts_dtype(cls, value):
        dtype = str(value or "").strip().lower()
        if dtype not in {"bfloat16", "float16", "float32"}:
            raise ValueError("Unsupported MOSS-TTS dtype")
        return dtype

    @model_validator(mode="before")
    @classmethod
    def migrate_landscape_transition_settings(cls, value):
        if isinstance(value, dict):
            data = dict(value)
            if "storyboard_transition_effects" not in data and "landscape_transition_effects" in data:
                data["storyboard_transition_effects"] = data["landscape_transition_effects"]
            return data
        return value

    @field_validator("storyboard_transition_effects")
    @classmethod
    def validate_storyboard_transition_effects(cls, value):
        names = [item.name for item in value]
        if len(names) != len(set(names)) or set(names) != set(STORYBOARD_TRANSITION_NAMES):
            raise ValueError("Storyboard transition settings must contain each supported effect once")
        enabled = [item for item in value if item.enabled]
        if enabled and any(item.percentage <= 0 for item in enabled):
            raise ValueError("Enabled storyboard transitions must have a positive percentage")
        if enabled and sum(item.percentage for item in enabled) != 100:
            raise ValueError("Enabled storyboard transition percentages must total 100")
        by_name = {item.name: item for item in value}
        return [by_name[name] for name in STORYBOARD_TRANSITION_NAMES]

    @model_validator(mode="after")
    def validate_storyboard_transition_ranges(self):
        if self.storyboard_transition_group_min_clips > self.storyboard_transition_group_max_clips:
            raise ValueError("Minimum clips per transition group cannot exceed maximum clips")
        if self.storyboard_transition_min_per_group > self.storyboard_transition_max_per_group:
            raise ValueError("Minimum transitions per group cannot exceed maximum transitions")
        if self.subtitle_min_cue_duration_ms >= self.subtitle_max_cue_duration_ms:
            raise ValueError("Minimum subtitle cue duration must be shorter than maximum duration")
        return self

    @field_validator("qwen_tts_device", "qwen_tts_language", "index_tts_device", "moss_tts_device")
    @classmethod
    def non_empty_qwen_setting(cls, value):
        text = str(value or "").strip()
        if not text:
            raise ValueError("Qwen3-TTS device and language cannot be empty")
        return text

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
        "index_tts_root",
        "index_tts_python",
        "index_tts_model_dir",
        "moss_tts_root",
        "moss_tts_python",
        "moss_tts_model_dir",
        "moss_tts_codec_dir",
        "image_generation_model_path",
        "image_generation_config_dir",
        "image_generation_python",
        "duix_host_shared_dir",
    ):
        value = getattr(settings, field_name)
        if value is not None:
            setattr(settings, field_name, value.expanduser().resolve())
    return settings


def _ensure_workspace(settings: Settings) -> None:
    settings.workspace_dir.mkdir(parents=True, exist_ok=True)
    for name in ("projects", "voices", "voice_generations", "templates"):
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
