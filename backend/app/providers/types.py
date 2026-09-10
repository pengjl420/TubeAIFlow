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
    STRUCTURED_OUTPUT = "structured_output"
    LONG_CONTEXT = "long_context"


class ProviderBillingMode(StrEnum):
    LOCAL = "local"
    EXTERNAL = "external"


class ProviderCostEstimate(BaseModel):
    billing: ProviderBillingMode
    estimated_usd: float = Field(ge=0)
    usage: dict[str, int | float | str] = Field(default_factory=dict)


class ProviderHealth(BaseModel):
    available: bool
    error: str | None = None


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
