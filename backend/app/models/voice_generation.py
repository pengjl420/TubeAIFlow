from sqlmodel import Field, SQLModel

from app.shared.time import utc_now_iso


class VoiceGenerationTask(SQLModel, table=True):
    __tablename__ = "voice_generation_tasks"

    id: str = Field(primary_key=True)
    voice_profile_id: str = Field(index=True)
    voice_profile_name: str
    text: str
    output_filename: str
    output_path: str | None = None
    duration: float | None = None
    status: str = Field(default="queued", index=True)
    queue_sequence: int = Field(index=True)
    attempt_count: int = 0
    error_message: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    started_at: str | None = None
    finished_at: str | None = None
