from sqlmodel import Field, SQLModel

from app.utils.time_utils import utc_now_iso


class BatchJob(SQLModel, table=True):
    __tablename__ = "batch_jobs"

    id: str = Field(primary_key=True)
    name: str
    status: str = Field(default="draft", index=True)
    total: int = 0
    completed: int = 0
    failed: int = 0
    config_json: str = "{}"
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    started_at: str | None = None
    finished_at: str | None = None

