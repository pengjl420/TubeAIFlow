from sqlmodel import Field, SQLModel

from app.utils.time_utils import utc_now_iso


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
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
