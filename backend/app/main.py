import logging
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session

from app.api import (
    avatars,
    batches,
    exports,
    local_video_merge,
    media_library,
    projects,
    providers,
    quality,
    renders,
    segments,
    settings,
    storyboard,
    subtitles,
    tasks,
    tts,
    voices,
    voice_generation,
)
from app.database import create_db_and_tables, engine
from app.services.avatar import avatar_service
from app.services.image_generation import image_generation_service
from app.services.narration import voice_generation_queue, voice_profile_service
from app.services.rendering import local_video_merge_queue
from app.services.settings import system_settings_service
from app.services.settings import cleanup_service
from app.services.settings import llm_model_manager
from app.services.tasks import task_worker


logger = logging.getLogger(__name__)
image_generation_service.bind_builtin_provider_runtimes()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    create_db_and_tables()
    with Session(engine) as session:
        system_settings_service.migrate_plaintext_secrets(session)
        voice_profile_service.migrate_profile_directories(session)
        voice_profile_service.migrate_profile_language_engines(session)
    avatar_service.recover_and_start_worker()
    local_video_merge_queue.recover_and_start_worker()
    voice_generation_queue.recover_and_start_worker()
    task_worker.recover_and_start_worker()
    cleanup_stop, cleanup_thread = cleanup_service.start_worker()
    llm_model_manager.recover_and_start_worker()
    try:
        yield
    finally:
        cleanup_stop.set()
        await asyncio.to_thread(cleanup_thread.join)


app = FastAPI(title="TubeAiFolw Engine", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {
        "success": True,
        "data": {
            "status": "ok",
            "product": "TubeAiFolw",
            "engine_version": app.version,
            "mode": "local-web-development",
        },
    }


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": str(detail.get("error") or exc.detail),
            "code": str(detail.get("code") or f"HTTP_{exc.status_code}"),
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    location = ".".join(str(item) for item in first.get("loc", ()))
    message = str(first.get("msg") or "请求参数校验失败")
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "error": f"{location}: {message}" if location else message,
            "code": "REQUEST_VALIDATION_FAILED",
        },
    )


@app.exception_handler(Exception)
async def unexpected_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled engine error for %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "引擎发生未预期错误，请查看本地日志",
            "code": "ENGINE_INTERNAL_ERROR",
        },
    )


app.include_router(avatars.router, prefix="/api")
app.include_router(batches.router, prefix="/api")
app.include_router(exports.router, prefix="/api")
app.include_router(local_video_merge.router, prefix="/api")
app.include_router(media_library.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(providers.router, prefix="/api")
app.include_router(quality.router, prefix="/api")
app.include_router(renders.router, prefix="/api")
app.include_router(segments.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(storyboard.router, prefix="/api")
app.include_router(subtitles.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(tts.router, prefix="/api")
app.include_router(voices.router, prefix="/api")
app.include_router(voice_generation.router, prefix="/api")
