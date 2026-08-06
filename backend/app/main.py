from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session

from app.api import (
    avatars,
    batches,
    exports,
    local_video_merge,
    projects,
    quality,
    renders,
    segments,
    settings,
    storyboard,
    subtitles,
    tasks,
    tts,
    voices,
)
from app.database import create_db_and_tables, engine
from app.services.narration import voice_profile_service
from app.services.avatar import avatar_service
from app.services.rendering import local_video_merge_queue
from app.services.tasks import task_worker


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
    avatar_service.recover_and_start_worker()
    task_worker.recover_and_start_worker()
    local_video_merge_queue.recover_and_start_worker()


@app.get("/api/health")
def health() -> dict:
    return {"success": True, "data": {"status": "ok"}}


app.include_router(projects.router, prefix="/api")
app.include_router(avatars.router, prefix="/api")
app.include_router(batches.router, prefix="/api")
app.include_router(voices.router, prefix="/api")
app.include_router(segments.router, prefix="/api")
app.include_router(tts.router, prefix="/api")
app.include_router(subtitles.router, prefix="/api")
app.include_router(exports.router, prefix="/api")
app.include_router(local_video_merge.router, prefix="/api")
app.include_router(renders.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(quality.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(storyboard.router, prefix="/api")
