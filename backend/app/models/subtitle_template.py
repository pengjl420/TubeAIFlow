from sqlmodel import Field, SQLModel

from app.utils.time_utils import utc_now_iso


class SubtitleTemplate(SQLModel, table=True):
    __tablename__ = "subtitle_templates"

    id: str = Field(primary_key=True)
    name: str
    language: str
    config_json: str
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
