from datetime import datetime

from sqlmodel import Field, SQLModel


class SubtitleTemplate(SQLModel, table=True):
    __tablename__ = "subtitle_templates"

    id: str = Field(primary_key=True)
    name: str
    language: str
    config_json: str
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
