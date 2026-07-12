from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import exports, projects, segments, subtitles, tts, videos, voices
from app.database import create_db_and_tables


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


@app.get("/api/health")
def health() -> dict:
    return {"success": True, "data": {"status": "ok"}}


app.include_router(projects.router, prefix="/api")
app.include_router(voices.router, prefix="/api")
app.include_router(segments.router, prefix="/api")
app.include_router(tts.router, prefix="/api")
app.include_router(subtitles.router, prefix="/api")
app.include_router(exports.router, prefix="/api")
app.include_router(videos.router, prefix="/api")
