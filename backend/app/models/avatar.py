from sqlmodel import Field, SQLModel

from app.shared.time import utc_now_iso


class AvatarProfile(SQLModel, table=True):
    __tablename__ = "avatar_profiles"

    id: str = Field(primary_key=True)
    name: str
    template_video_path: str
    duration_ms: int | None = None
    width: int | None = None
    height: int | None = None
    enabled: bool = Field(default=True, index=True)
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class AvatarGenerationTask(SQLModel, table=True):
    __tablename__ = "avatar_generation_tasks"

    id: str = Field(primary_key=True)
    avatar_profile_id: str = Field(index=True)
    audio_path: str
    output_filename: str
    chunk_seconds: int = 420
    context_ms: int = 800
    audio_duration_ms: int = 0
    status: str = Field(default="queued", index=True)
    queue_sequence: int = Field(index=True)
    total_chunks: int = 0
    completed_chunks: int = 0
    current_chunk: int | None = None
    progress: float = 0
    result_path: str | None = None
    continuity_report_path: str | None = None
    error_message: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    started_at: str | None = None
    finished_at: str | None = None


class AvatarClip(SQLModel, table=True):
    __tablename__ = "avatar_clips"

    id: str = Field(primary_key=True)
    task_id: str = Field(index=True)
    clip_index: int
    start_ms: int
    end_ms: int
    generation_start_ms: int = 0
    generation_end_ms: int = 0
    trim_start_ms: int = 0
    trim_end_ms: int = 0
    audio_path: str
    duix_task_code: str
    status: str = Field(default="pending", index=True)
    progress: float = 0
    output_path: str | None = None
    actual_duration_ms: int | None = None
    error_message: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
