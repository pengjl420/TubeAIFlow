from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session

from app.api import avatars, local_video_merge, settings, voices, voice_generation
from app.database import create_db_and_tables, engine
from app.services.avatar import avatar_service
from app.services.narration import voice_generation_queue, voice_profile_service
from app.services.rendering import local_video_merge_queue


app = FastAPI(title="TubeAIFlow", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    create_db_and_tables()
    with Session(engine) as session:
        voice_profile_service.migrate_profile_directories(session)
        voice_profile_service.migrate_profile_language_engines(session)
    avatar_service.recover_and_start_worker()
    local_video_merge_queue.recover_and_start_worker()
    voice_generation_queue.recover_and_start_worker()


@app.get("/api/health")
def health() -> dict:
    return {"success": True, "data": {"status": "ok"}}


app.include_router(avatars.router, prefix="/api")
app.include_router(local_video_merge.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(voices.router, prefix="/api")
app.include_router(voice_generation.router, prefix="/api")
