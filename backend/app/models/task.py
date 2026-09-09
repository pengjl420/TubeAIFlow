from sqlmodel import Field, SQLModel

from app.shared.time import utc_now_iso
from app.domain.states import TaskStatus


class TaskRun(SQLModel, table=True):
    __tablename__ = "task_runs"

    id: str = Field(primary_key=True)
    project_id: str = Field(index=True)
    batch_id: str | None = Field(default=None, index=True)
    batch_item_id: str | None = Field(default=None, index=True)
    workflow: str = Field(default="narration_generation", index=True)
    job_type: str = Field(default="project_workflow", index=True)
    scene_id: str | None = Field(default=None, index=True)
    resource_class: str = Field(default="cpu", index=True)
    status: str = Field(default=TaskStatus.QUEUED.value, index=True)
    current_stage: str = Field(default="segmenting", index=True)
    include_video: bool = False
    queue_sequence: int = Field(index=True)
    attempt_count: int = 0
    compensation_count: int = 0
    cancel_requested: bool = False
    pause_requested: bool = False
    progress: float = 0.0
    max_retries: int = 0
    error_code: str | None = None
    request_json: str = "{}"
    result_json: str = "{}"
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
