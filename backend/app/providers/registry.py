from collections.abc import Iterable
from dataclasses import dataclass
from typing import TypeVar, cast

from app.providers.runtime import ProviderRuntime
from app.providers.types import ProviderCapability, ProviderCategory, ProviderMetadata


RuntimeT = TypeVar("RuntimeT", bound=ProviderRuntime)


@dataclass(frozen=True, slots=True)
class ProviderRegistration:
    metadata: ProviderMetadata
    runtime: ProviderRuntime | None = None


class ProviderRegistry:
    """Stable provider metadata registry used by Engine and Web UI.

    Generation remains in the existing tested integrations during the compatibility
    phase. New provider implementations must register here before business services
    can select them.
    """

    def __init__(self) -> None:
        self._providers: dict[str, ProviderRegistration] = {}

    def register(
        self, metadata: ProviderMetadata, runtime: ProviderRuntime | None = None
    ) -> None:
        if metadata.id in self._providers:
            raise ValueError(f"Provider is already registered: {metadata.id}")
        self._providers[metadata.id] = ProviderRegistration(metadata, runtime)

    def bind_runtime(self, provider_id: str, runtime: ProviderRuntime) -> None:
        """Attach an executable adapter to already-registered provider metadata."""
        normalized = self.normalize_id(provider_id)
        try:
            registration = self._providers[normalized]
        except KeyError as exc:
            raise ValueError(f"Unsupported provider: {provider_id}") from exc
        self._providers[normalized] = ProviderRegistration(registration.metadata, runtime)

    def get(self, provider_id: str) -> ProviderMetadata:
        normalized = self.normalize_id(provider_id)
        try:
            return self._providers[normalized].metadata
        except KeyError as exc:
            raise ValueError(f"Unsupported provider: {provider_id}") from exc

    def runtime(self, provider_id: str, runtime_type: type[RuntimeT]) -> RuntimeT:
        normalized = self.normalize_id(provider_id)
        try:
            runtime = self._providers[normalized].runtime
        except KeyError as exc:
            raise ValueError(f"Unsupported provider: {provider_id}") from exc
        if runtime is None:
            raise ValueError(f"Provider has no executable runtime: {provider_id}")
        if not isinstance(runtime, runtime_type):
            raise TypeError(
                f"Provider {provider_id} runtime is not {runtime_type.__name__}"
            )
        return cast(RuntimeT, runtime)

    def is_executable(self, provider_id: str) -> bool:
        normalized = self.normalize_id(provider_id)
        registration = self._providers.get(normalized)
        return bool(registration and registration.runtime is not None)

    def list(self, category: ProviderCategory | None = None) -> list[ProviderMetadata]:
        values: Iterable[ProviderMetadata] = (
            item.metadata for item in self._providers.values()
        )
        if category is not None:
            values = (item for item in values if item.category == category)
        return sorted(values, key=lambda item: item.id)

    def normalize_id(self, provider_id: str) -> str:
        value = str(provider_id or "").strip().lower()
        if value in self._providers:
            return value
        qualified = f"tts.{value}"
        return qualified if qualified in self._providers else value

    def legacy_ids(self, category: ProviderCategory) -> set[str]:
        return {item.legacy_id for item in self.list(category)}


provider_registry = ProviderRegistry()


def _register_builtin_providers() -> None:
    shared = frozenset(
        {
            ProviderCapability.VOICE_CLONE,
            ProviderCapability.REFERENCE_AUDIO,
            ProviderCapability.LOCAL_INFERENCE,
        }
    )
    providers = (
        ProviderMetadata(
            id="tts.qwen3_tts",
            category=ProviderCategory.TTS,
            display_name="Qwen3-TTS",
            model_id="qwen3-tts",
            capabilities=shared | {ProviderCapability.REFERENCE_TEXT},
            configuration_fields=("qwen_tts_root", "qwen_tts_model_dir", "qwen_tts_device"),
        ),
        ProviderMetadata(
            id="tts.index_tts",
            category=ProviderCategory.TTS,
            display_name="IndexTTS",
            model_id="index-tts",
            capabilities=shared,
            configuration_fields=("index_tts_root", "index_tts_model_dir", "index_tts_device"),
        ),
        ProviderMetadata(
            id="tts.moss_tts",
            category=ProviderCategory.TTS,
            display_name="MOSS-TTS",
            model_id="moss-tts-local",
            capabilities=shared,
            configuration_fields=("moss_tts_root", "moss_tts_model_dir", "moss_tts_device"),
        ),
        ProviderMetadata(
            id="tts.cosyvoice",
            category=ProviderCategory.TTS,
            display_name="CosyVoice",
            model_id="fun-cosyvoice",
            capabilities=shared
            | {ProviderCapability.REFERENCE_TEXT, ProviderCapability.SPEED},
            configuration_fields=("cosyvoice_root", "cosyvoice_model_dir"),
        ),
    )
    for provider in providers:
        provider_registry.register(provider)

    llm_providers = (
        ProviderMetadata(
            id="llm.local_qwen",
            category=ProviderCategory.LLM,
            display_name="Local Qwen",
            model_id="qwen3-8b-q4_k_m",
            capabilities=frozenset(
                {
                    ProviderCapability.LOCAL_INFERENCE,
                    ProviderCapability.STRUCTURED_OUTPUT,
                    ProviderCapability.LONG_CONTEXT,
                }
            ),
            configuration_fields=(
                "local_llm_base_url",
                "local_llm_model",
            ),
        ),
        ProviderMetadata(
            id="llm.deepseek",
            category=ProviderCategory.LLM,
            display_name="DeepSeek",
            model_id="deepseek-v4-flash",
            local=False,
            capabilities=frozenset(
                {ProviderCapability.STRUCTURED_OUTPUT, ProviderCapability.LONG_CONTEXT}
            ),
            configuration_fields=("deepseek_base_url", "deepseek_model", "deepseek_api_key"),
        ),
    )
    for provider in llm_providers:
        provider_registry.register(provider)


_register_builtin_providers()
