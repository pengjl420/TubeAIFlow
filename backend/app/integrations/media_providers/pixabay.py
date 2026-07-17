from datetime import UTC, datetime, timedelta

import httpx

from app.integrations.media_providers.common import (
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderSearchResponse,
)
from app.schemas.media import RemoteMediaCandidate


class PixabayClient:
    SEARCH_URL = "https://pixabay.com/api/videos/"

    def __init__(self, api_key: str, client: httpx.Client | None = None):
        self.api_key = api_key
        self.client = client

    def search_videos(self, query: str, limit: int) -> ProviderSearchResponse:
        client = self.client or httpx.Client(timeout=30)
        try:
            response = client.get(
                self.SEARCH_URL,
                params={
                    "key": self.api_key,
                    "q": query,
                    "orientation": "horizontal",
                    "safesearch": "true",
                    "per_page": max(3, min(limit, 200)),
                },
            )
        except httpx.RequestError as exc:
            raise ProviderRequestError("Pixabay 请求失败，请检查网络连接") from exc
        finally:
            if self.client is None:
                client.close()

        reset_seconds = _integer(response.headers.get("X-RateLimit-Reset"))
        reset_at = (datetime.now(UTC) + timedelta(seconds=reset_seconds or 60)).isoformat()
        if response.status_code == 429:
            raise ProviderRateLimitError("Pixabay 请求频率已达到限制", reset_at)
        if response.status_code >= 400:
            raise ProviderRequestError(f"Pixabay API 返回 HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderRequestError("Pixabay API 返回了无效数据") from exc

        candidates = []
        for item in data.get("hits", []):
            selected = _select_video(item.get("videos") or {})
            if not selected or not selected.get("url"):
                continue
            tags = [value.strip() for value in str(item.get("tags") or "").split(",") if value.strip()]
            candidates.append(
                RemoteMediaCandidate(
                    provider="pixabay",
                    asset_id=str(item.get("id")),
                    page_url=str(item.get("pageURL") or "https://pixabay.com"),
                    preview_url=selected.get("thumbnail"),
                    download_url=str(selected["url"]),
                    width=_integer(selected.get("width")),
                    height=_integer(selected.get("height")),
                    duration_ms=_duration_ms(item.get("duration")),
                    author=str(item.get("user") or ""),
                    title=" ".join(tags) or query,
                    tags=tags or query.split(),
                    query=query,
                )
            )
        return ProviderSearchResponse(
            candidates=candidates,
            rate_limit=_integer(response.headers.get("X-RateLimit-Limit")),
            remaining=_integer(response.headers.get("X-RateLimit-Remaining")),
            reset_at=reset_at,
        )


def _select_video(videos: dict) -> dict | None:
    for name in ("medium", "large", "small", "tiny"):
        value = videos.get(name)
        if value and value.get("url"):
            return value
    return None


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
