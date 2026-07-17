import hashlib
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlmodel import Session, select

from app.config import get_settings
from app.models.media import MediaFile, MediaShot
from app.schemas.media import RemoteMediaCandidate
from app.schemas.storyboard import StoryboardContent
from app.services.media_library import ingestion_service, media_provider_service


MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024
ALLOWED_DOWNLOAD_DOMAINS = {
    "pexels": ("pexels.com",),
    "pixabay": ("pixabay.com",),
}


def fetch_provider_candidates(
    session: Session,
    provider: str,
    storyboard: StoryboardContent,
) -> dict:
    settings = get_settings()
    search = media_provider_service.search_provider(
        session,
        provider,
        [
            storyboard.primary_query,
            *storyboard.alternative_queries,
            storyboard.fallback_category,
        ],
        limit=20,
    )
    downloaded = []
    errors = []
    for raw in search.get("candidates", [])[: settings.media_search_download_limit]:
        candidate = RemoteMediaCandidate.model_validate(raw)
        try:
            media_file = _download_and_ingest(session, candidate)
            downloaded.append(media_file.id)
        except (OSError, RuntimeError, ValueError, httpx.HTTPError) as exc:
            errors.append({"asset_id": candidate.asset_id, "error": str(exc)})
    return {
        "provider": provider,
        "status": search["status"],
        "reset_at": search.get("reset_at"),
        "downloaded": downloaded,
        "errors": errors,
    }


def _download_and_ingest(session: Session, candidate: RemoteMediaCandidate) -> MediaFile:
    existing = session.exec(
        select(MediaFile).where(
            MediaFile.provider == candidate.provider,
            MediaFile.provider_asset_id == candidate.asset_id,
        )
    ).first()
    if existing:
        existing_path = Path(existing.path)
        if not existing_path.is_file():
            existing_path.parent.mkdir(parents=True, exist_ok=True)
            _download(candidate, existing_path)
        _ensure_ingested(session, existing)
        return existing

    download_path = _download_path(candidate)
    if not download_path.is_file():
        _download(candidate, download_path)
    media_file, _ = ingestion_service.import_remote_asset(session, download_path, candidate)
    _ensure_ingested(session, media_file)
    return media_file


def _ensure_ingested(session: Session, media_file: MediaFile) -> None:
    shots = session.exec(select(MediaShot).where(MediaShot.media_file_id == media_file.id)).all()
    if any(shot.vector_id is None for shot in shots):
        result = ingestion_service.ingest_asset(session, media_file.id)
        if result["errors"] and len(result["errors"]) == len(shots):
            raise RuntimeError(f"在线素材 {media_file.provider_asset_id} 处理失败")


def _download_path(candidate: RemoteMediaCandidate) -> Path:
    suffix = Path(urlparse(candidate.download_url).path).suffix.lower()
    if suffix not in {".mp4", ".mov", ".webm"}:
        suffix = ".mp4"
    url_hash = hashlib.sha256(candidate.download_url.encode("utf-8")).hexdigest()[:10]
    directory = get_settings().workspace_dir / "assets" / "downloads" / candidate.provider
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{candidate.asset_id}_{url_hash}{suffix}"


def _download(candidate: RemoteMediaCandidate, destination: Path) -> None:
    parsed = urlparse(candidate.download_url)
    allowed = ALLOWED_DOWNLOAD_DOMAINS.get(candidate.provider, ())
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not any(
        hostname == domain or hostname.endswith(f".{domain}") for domain in allowed
    ):
        raise ValueError(f"{candidate.provider} 返回了不受信任的下载地址")

    temporary = destination.with_suffix(destination.suffix + ".part")
    total = 0
    try:
        with httpx.stream("GET", candidate.download_url, timeout=120, follow_redirects=True) as response:
            final_host = (response.url.host or "").lower()
            if not any(
                final_host == domain or final_host.endswith(f".{domain}") for domain in allowed
            ):
                raise ValueError(f"{candidate.provider} 下载发生了不受信任的重定向")
            if response.status_code >= 400:
                raise RuntimeError(
                    f"{candidate.provider} 素材下载返回 HTTP {response.status_code}"
                )
            with temporary.open("wb") as output:
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES:
                        raise ValueError("在线素材超过 500 MB 下载限制")
                    output.write(chunk)
        temporary.replace(destination)
    except httpx.RequestError as exc:
        raise RuntimeError(f"{candidate.provider} 素材下载失败，请检查网络连接") from exc
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)
