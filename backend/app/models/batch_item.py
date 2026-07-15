from sqlmodel import Field, SQLModel, UniqueConstraint

from app.utils.time_utils import utc_now_iso


class BatchItem(SQLModel, table=True):
    __tablename__ = "batch_items"
    __table_args__ = (UniqueConstraint("batch_id", "order_index"),)

    id: str = Field(primary_key=True)
    batch_id: str = Field(index=True)
    project_id: str = Field(index=True)
    order_index: int
    original_filename: str
    status: str = Field(default="pending", index=True)
    current_stage: str = "script_saved"
    error_message: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    started_at: str | None = None
    finished_at: str | None = None

