from datetime import UTC, datetime, timedelta

import httpx

from app.integrations.media_providers.common import (
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderSearchResponse,
)
from app.schemas.media import RemoteMediaCandidate


class PexelsClient:
    SEARCH_URL = "https://api.pexels.com/v1/videos/search"

    def __init__(self, api_key: str, client: httpx.Client | None = None):
        self.api_key = api_key
        self.client = client

    def search_videos(self, query: str, limit: int) -> ProviderSearchResponse:
        client = self.client or httpx.Client(timeout=30)
        try:
            response = client.get(
                self.SEARCH_URL,
                headers={"Authorization": self.api_key},
                params={
                    "query": query,
                    "orientation": "landscape",
                    "size": "large",
                    "per_page": max(1, min(limit, 80)),
                },
            )
        except httpx.RequestError as exc:
            raise ProviderRequestError("Pexels 请求失败，请检查网络连接") from exc
        finally:
            if self.client is None:
                client.close()

        reset_at = _pexels_reset_at(response.headers.get("X-Ratelimit-Reset"))
        if response.status_code == 429:
            raise ProviderRateLimitError("Pexels 请求额度已用完", reset_at)
        if response.status_code >= 400:
            raise ProviderRequestError(f"Pexels API 返回 HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderRequestError("Pexels API 返回了无效数据") from exc

        candidates = []
        for item in data.get("videos", []):
            selected = _select_video_file(item.get("video_files", []))
            if not selected or not selected.get("link"):
                continue
            user = item.get("user") or {}
            candidates.append(
                RemoteMediaCandidate(
                    provider="pexels",
                    asset_id=str(item.get("id")),
                    page_url=str(item.get("url") or "https://www.pexels.com"),
                    preview_url=_picture(item),
                    download_url=str(selected["link"]),
                    width=_integer(selected.get("width") or item.get("width")),
                    height=_integer(selected.get("height") or item.get("height")),
                    duration_ms=_duration_ms(item.get("duration")),
                    author=str(user.get("name") or ""),
                    title=query,
                    tags=query.split(),
                    query=query,
                )
            )
        return ProviderSearchResponse(
            candidates=candidates,
            rate_limit=_integer(response.headers.get("X-Ratelimit-Limit")),
            remaining=_integer(response.headers.get("X-Ratelimit-Remaining")),
            reset_at=reset_at,
        )


def _select_video_file(files: list[dict]) -> dict | None:
    landscape = [
        item for item in files
        if _integer(item.get("width")) and _integer(item.get("height"))
        and int(item["width"]) >= int(item["height"])
    ]
    if not landscape:
        return None
    return min(landscape, key=lambda item: abs(int(item["width"]) - 1920))


def _picture(item: dict) -> str | None:
    pictures = item.get("video_pictures") or []
    return str(pictures[0].get("picture")) if pictures and pictures[0].get("picture") else None


def _integer(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _duration_ms(value) -> int | None:
    try:
        return round(float(value) * 1000)
    except (TypeError, ValueError):
        return None


def _pexels_reset_at(value: str | None) -> str:
    try:
        return datetime.fromtimestamp(int(value), UTC).isoformat()
    except (TypeError, ValueError, OSError):
        return (datetime.now(UTC) + timedelta(hours=1)).isoformat()
