from collections.abc import Iterable

from app.providers.types import ProviderCapability, ProviderCategory, ProviderMetadata


class ProviderRegistry:
    """Stable provider metadata registry used by Engine and Web UI.

    Generation remains in the existing tested integrations during the compatibility
    phase. New provider implementations must register here before business services
    can select them.
    """

    def __init__(self) -> None:
        self._providers: dict[str, ProviderMetadata] = {}

    def register(self, metadata: ProviderMetadata) -> None:
        if metadata.id in self._providers:
            raise ValueError(f"Provider is already registered: {metadata.id}")
        self._providers[metadata.id] = metadata

    def get(self, provider_id: str) -> ProviderMetadata:
        normalized = self.normalize_id(provider_id)
        try:
            return self._providers[normalized]
        except KeyError as exc:
            raise ValueError(f"Unsupported provider: {provider_id}") from exc

    def list(self, category: ProviderCategory | None = None) -> list[ProviderMetadata]:
        values: Iterable[ProviderMetadata] = self._providers.values()
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


_register_builtin_providers()
