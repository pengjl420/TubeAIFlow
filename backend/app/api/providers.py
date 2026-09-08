import httpx
from fastapi import APIRouter, HTTPException, Query

from app.config import get_settings
from app.providers import ProviderCategory, provider_registry
from app.services.settings import llm_model_manager


router = APIRouter(tags=["providers"])


@router.get("/models/llm")
def list_llm_models() -> dict:
    return {"success": True, "data": llm_model_manager.list_models()}


@router.post("/models/llm/{model_id}/download", status_code=202)
def download_llm_model(model_id: str) -> dict:
    try:
        job = llm_model_manager.enqueue_download(model_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": str(exc), "code": "LLM_MODEL_NOT_FOUND"},
        ) from exc
    return {"success": True, "data": job}


@router.get("/models/llm/downloads/{job_id}")
def get_llm_model_download(job_id: str) -> dict:
    try:
        job = llm_model_manager.get_job(job_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": str(exc), "code": "MODEL_DOWNLOAD_NOT_FOUND"},
        ) from exc
    return {"success": True, "data": job}


@router.get("/providers/llm/status")
def get_llm_provider_status() -> dict:
    settings = get_settings()
    local_available = False
    local_error = None
    try:
        endpoint = settings.local_llm_base_url.rstrip("/")
        if endpoint.endswith("/v1"):
            endpoint = endpoint[:-3]
        endpoint += "/health"
        response = httpx.get(endpoint, timeout=1.5)
        response.raise_for_status()
        local_available = True
    except (httpx.HTTPError, OSError) as exc:
        local_error = str(exc)
    return {
        "success": True,
        "data": {
            "strategy": settings.storyboard_llm_strategy,
            "local": {
                "provider": "llm.local_qwen",
                "model": settings.local_llm_model,
                "available": local_available,
                "error": local_error,
            },
            "cloud": {
                "provider": "llm.deepseek",
                "model": settings.deepseek_model,
                "configured": bool(settings.deepseek_api_key.strip()),
            },
            "cache_enabled": settings.storyboard_llm_cache_enabled,
        },
    }


@router.get("/providers")
def list_providers(category: ProviderCategory | None = Query(default=None)) -> dict:
    settings = get_settings()
    return {
        "success": True,
        "data": [
            {
                **item.model_dump(mode="json"),
                "available": (
                    bool(settings.deepseek_api_key.strip())
                    if item.id == "llm.deepseek"
                    else True
                ),
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
