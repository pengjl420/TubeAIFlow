from sqlmodel import Field, SQLModel

from app.shared.time import utc_now_iso


class TaskRun(SQLModel, table=True):
    __tablename__ = "task_runs"

    id: str = Field(primary_key=True)
    project_id: str = Field(index=True)
    batch_id: str | None = Field(default=None, index=True)
    batch_item_id: str | None = Field(default=None, index=True)
    workflow: str = Field(default="narration_generation", index=True)
    status: str = Field(default="queued", index=True)
    current_stage: str = Field(default="segmenting", index=True)
    include_video: bool = False
    queue_sequence: int = Field(index=True)
    attempt_count: int = 0
    compensation_count: int = 0
    cancel_requested: bool = False
    checkpoint_json: str = "{}"
    config_snapshot_json: str = "{}"
    error_message: str | None = None
    lease_owner: str | None = None
    heartbeat_at: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    started_at: str | None = None
    finished_at: str | None = None
    last_recovered_at: str | None = None
