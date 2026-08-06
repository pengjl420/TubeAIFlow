from sqlmodel import Field, SQLModel

from app.shared.time import utc_now_iso


class LocalVideoMergeTask(SQLModel, table=True):
    __tablename__ = "local_video_merge_tasks"

    id: str = Field(primary_key=True)
    media_dir: str
    output_dir: str
    output_filename: str
    target_duration: float
    status: str = Field(default="queued", index=True)
    queue_sequence: int = Field(index=True)
    attempt_count: int = 0
    result_json: str = "{}"
    error_message: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    started_at: str | None = None
    finished_at: str | None = None
