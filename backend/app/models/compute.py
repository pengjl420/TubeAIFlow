from sqlmodel import Field, SQLModel
from app.shared.time import utc_now_iso


class ComputeConnection(SQLModel, table=True):
    __tablename__ = "compute_connections"

    id: str = Field(primary_key=True)
    name: str
    provider: str = "compute.compshare"
    region: str = ""
    zone: str = ""
    project_id: str = ""
    instance_id: str = ""
    credential_id: str
    config_version: int = 1
    management_mode: str = "manual"
    created_at: str = Field(default_factory=utc_now_iso)
