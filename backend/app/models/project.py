from datetime import datetime

from sqlmodel import Field, SQLModel


class Project(SQLModel, table=True):
    __tablename__ = "projects"

    id: str = Field(primary_key=True)
    name: str
    script_raw_path: str | None = None
    script_clean_path: str | None = None
    reference_audio_path: str | None = None
    output_dir: str | None = None
    status: str = "created"
    config_json: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
