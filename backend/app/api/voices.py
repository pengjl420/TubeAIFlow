from fastapi import APIRouter


router = APIRouter(tags=["voices"])


@router.get("/voices")
def list_voices() -> dict:
    return {"success": True, "data": []}
