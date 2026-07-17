import hashlib
import json
import re
from datetime import UTC, datetime, timedelta

from sqlmodel import Session

from app.config import get_settings
from app.integrations.media_providers import PexelsClient, PixabayClient
from app.integrations.media_providers.common import ProviderRateLimitError, ProviderRequestError
from app.models.media import MediaProviderState, MediaQueryCache
from app.schemas.media import RemoteMediaCandidate
from app.shared.time import utc_now_iso


PROVIDER_ORDER = ("pexels", "pixabay")


def search_provider(
    session: Session,
    provider: str,
    queries: list[str],
    limit: int = 20,
) -> dict:
    settings = get_settings()
    api_key = _api_key(settings, provider)
    if not api_key:
        return {"provider": provider, "status": "unconfigured", "candidates": []}
    state = _current_state(session, provider)
    if state and state.status == "cooldown" and not _reset_elapsed(state.reset_at):
        return {
            "provider": provider,
            "status": "cooldown",
            "reset_at": state.reset_at,
            "candidates": [],
        }
    if state and state.status == "cooldown":
        reset_provider_state(session, provider)

    candidates: list[RemoteMediaCandidate] = []
    seen = set()
    used_cache = True
    for query in _normalized_queries(queries):
        cached = _read_cache(session, provider, query)
        if cached is None:
            used_cache = False
            try:
                response = _client(provider, api_key).search_videos(query, limit)
            except ProviderRateLimitError as exc:
                _save_state(session, provider, "cooldown", reset_at=exc.reset_at, error=str(exc))
                return {
                    "provider": provider,
                    "status": "cooldown",
                    "reset_at": exc.reset_at,
                    "candidates": [item.model_dump(mode="json") for item in candidates],
                }
            except ProviderRequestError as exc:
                _save_state(session, provider, "error", error=str(exc))
                return {
                    "provider": provider,
                    "status": "error",
                    "error": str(exc),
                    "candidates": [item.model_dump(mode="json") for item in candidates],
                }
            _save_cache(session, provider, query, response.candidates)
            _save_state(
                session,
                provider,
                "available",
                rate_limit=response.rate_limit,
                remaining=response.remaining,
                reset_at=response.reset_at,
            )
            current = response.candidates
        else:
            current = cached
        for item in current:
            identity = (item.provider, item.asset_id)
            if identity in seen:
                continue
            seen.add(identity)
            candidates.append(item)
            if len(candidates) >= limit:
                break
        if len(candidates) >= limit:
            break
    if not _current_state(session, provider):
        _save_state(session, provider, "available")
    return {
        "provider": provider,
        "status": "available",
        "cached": used_cache,
        "candidates": [item.model_dump(mode="json") for item in candidates],
    }


def get_provider_statuses(session: Session) -> list[dict]:
    settings = get_settings()
    result = []
    for provider in PROVIDER_ORDER:
        configured = bool(_api_key(settings, provider))
        state = _current_state(session, provider)
        if state and state.status == "cooldown" and _reset_elapsed(state.reset_at):
            _save_state(session, provider, "available")
            state = _current_state(session, provider)
        result.append(
            {
                "provider": provider,
                "configured": configured,
                "status": state.status if configured and state else ("available" if configured else "unconfigured"),
                "rate_limit": state.rate_limit if state else None,
                "remaining": state.remaining if state else None,
                "reset_at": state.reset_at if state else None,
                "last_error": state.last_error if state else None,
                "updated_at": state.updated_at if state else None,
            }
        )
    return result


def reset_provider_state(session: Session, provider: str) -> None:
    state = session.get(MediaProviderState, provider) or MediaProviderState(provider=provider)
    state.status = "available"
    state.rate_limit = None
    state.remaining = None
    state.reset_at = None
    state.last_error = None
    state.updated_at = utc_now_iso()
    session.add(state)
    session.commit()


def _client(provider: str, api_key: str):
    if provider == "pexels":
        return PexelsClient(api_key)
    if provider == "pixabay":
        return PixabayClient(api_key)
    raise ValueError(f"Unknown media provider: {provider}")


def _api_key(settings, provider: str) -> str:
    return str(getattr(settings, f"{provider}_api_key", "") or "").strip()


def _normalized_queries(queries: list[str]) -> list[str]:
    result = []
    for value in queries:
        normalized = re.sub(r"\s+", " ", str(value or "").strip().lower())
        if normalized and normalized not in result:
            result.append(normalized)
    return result[:3]


def _cache_id(provider: str, query: str) -> str:
    raw = f"{provider}\0video\0{query}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _read_cache(
    session: Session,
    provider: str,
    query: str,
) -> list[RemoteMediaCandidate] | None:
    cache = session.get(MediaQueryCache, _cache_id(provider, query))
    if not cache or _reset_elapsed(cache.expires_at):
        return None
    try:
        values = json.loads(cache.response_json)
        return [RemoteMediaCandidate.model_validate(item) for item in values]
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def _save_cache(
    session: Session,
    provider: str,
    query: str,
    candidates: list[RemoteMediaCandidate],
) -> None:
    now = datetime.now(UTC)
    cache = MediaQueryCache(
        id=_cache_id(provider, query),
        provider=provider,
        query=query,
        response_json=json.dumps(
            [item.model_dump(mode="json") for item in candidates], ensure_ascii=False
        ),
        expires_at=(now + timedelta(hours=get_settings().media_search_cache_hours)).isoformat(),
        created_at=now.isoformat(),
    )
    session.merge(cache)
    session.commit()


def _current_state(session: Session, provider: str) -> MediaProviderState | None:
    return session.get(MediaProviderState, provider)


def _save_state(
    session: Session,
    provider: str,
    status: str,
    rate_limit: int | None = None,
    remaining: int | None = None,
    reset_at: str | None = None,
    error: str | None = None,
) -> None:
    state = session.get(MediaProviderState, provider) or MediaProviderState(provider=provider)
    state.status = status
    if rate_limit is not None:
        state.rate_limit = rate_limit
    if remaining is not None:
        state.remaining = remaining
    state.reset_at = reset_at
    state.last_error = error
    state.updated_at = utc_now_iso()
    session.add(state)
    session.commit()


def _reset_elapsed(value: str | None) -> bool:
    if not value:
        return True
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed <= datetime.now(UTC)
