from fastapi import APIRouter, HTTPException, Query

from app.providers import ProviderCategory, provider_registry


router = APIRouter(tags=["providers"])


@router.get("/providers")
def list_providers(category: ProviderCategory | None = Query(default=None)) -> dict:
    return {
        "success": True,
        "data": [
            {
                **item.model_dump(mode="json"),
                "available": True,
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
    return {
        "success": True,
        "data": {**item.model_dump(mode="json"), "available": True, "legacy_id": item.legacy_id},
    }
