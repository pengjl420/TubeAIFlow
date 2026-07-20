from pathlib import Path

from app.config import Settings, get_settings


REMOTE_PROVIDERS = {"pexels", "pixabay"}


def provider_storage_dir(provider: str, settings: Settings | None = None) -> Path:
    """Return the directory that owns downloaded and generated provider assets."""
    if provider not in REMOTE_PROVIDERS:
        raise ValueError(f"Unsupported remote media provider: {provider}")
    current = settings or get_settings()
    configured = getattr(current, f"{provider}_storage_dir")
    if configured is not None:
        return configured.resolve()
    return (current.workspace_dir / "assets" / "downloads" / provider).resolve()


def provider_download_dir(provider: str, settings: Settings | None = None) -> Path:
    return provider_storage_dir(provider, settings)


def media_preview_dir(
    media_id: str,
    provider: str,
    settings: Settings | None = None,
) -> Path:
    current = settings or get_settings()
    configured = getattr(current, f"{provider}_storage_dir", None)
    if provider in REMOTE_PROVIDERS and configured is not None:
        return (configured / "thumbnails" / media_id).resolve()
    return (current.workspace_dir / "assets" / media_id).resolve()
