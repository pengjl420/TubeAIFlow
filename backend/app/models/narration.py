from sqlmodel import Field, SQLModel

from app.shared.time import utc_now_iso


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


class VoiceProfile(SQLModel, table=True):
    __tablename__ = "voice_profiles"

    id: str = Field(primary_key=True)
    name: str
    reference_audio_path: str
    config_json: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class SubtitleTemplate(SQLModel, table=True):
    __tablename__ = "subtitle_templates"

    id: str = Field(primary_key=True)
    name: str
    language: str
    config_json: str
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
