from enum import StrEnum

from pydantic import BaseModel, Field


class ProviderCategory(StrEnum):
    TTS = "tts"
    IMAGE = "image"
    VIDEO = "video"
    LLM = "llm"
    STOCK = "stock"


class ProviderCapability(StrEnum):
    VOICE_CLONE = "voice_clone"
    REFERENCE_AUDIO = "reference_audio"
    REFERENCE_TEXT = "reference_text"
    SPEED = "speed"
    LOCAL_INFERENCE = "local_inference"
    NEGATIVE_PROMPT = "negative_prompt"
    SEED = "seed"
    ASYNC_TASK = "async_task"


class ProviderMetadata(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    category: ProviderCategory
    display_name: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    model_version: str = "unknown"
    local: bool = True
    capabilities: frozenset[ProviderCapability] = frozenset()
    configuration_fields: tuple[str, ...] = ()

    @property
    def legacy_id(self) -> str:
        return self.id.split(".", 1)[-1]
