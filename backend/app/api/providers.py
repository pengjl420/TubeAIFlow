from fastapi import APIRouter, HTTPException, Query

from app.config import get_settings
from app.providers import ProviderCategory, provider_registry


router = APIRouter(tags=["providers"])


def _provider_available(provider_id: str) -> bool:
    settings = get_settings()
    if provider_id == "llm.deepseek":
        return bool(settings.deepseek_api_key.strip())
    if provider_id.startswith("image.seedream_5"):
        return bool(settings.seedream_api_key.strip())
    return True


@router.get("/providers")
def list_providers(category: ProviderCategory | None = Query(default=None)) -> dict:
    return {
        "success": True,
        "data": [
            {
                **item.model_dump(mode="json"),
                "available": _provider_available(item.id),
                "legacy_id": item.legacy_id,
            }
            for item in provider_registry.list(category)
        ],
    }


@router.get("/providers/{provider_id:path}")
def get_provider(provider_id: str) -> dict:
    try:
        item = provider_registry.get(provider_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": str(exc), "code": "PROVIDER_NOT_FOUND"},
        ) from exc
    available = _provider_available(item.id)
    return {
        "success": True,
        "data": {
            **item.model_dump(mode="json"),
            "available": available,
            "legacy_id": item.legacy_id,
        },
    }
