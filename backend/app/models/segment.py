from sqlmodel import Field, SQLModel

from app.utils.time_utils import utc_now_iso


class Segment(SQLModel, table=True):
    __tablename__ = "segments"

    id: str = Field(primary_key=True)
    segment_id: str = Field(index=True)
    project_id: str = Field(index=True)
    segment_index: int
    text_zh: str
    text_en: str | None = None
    audio_path: str | None = None
    duration: float | None = None
    start_time: float | None = None
    end_time: float | None = None
    status: str = "pending"
    error_message: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
