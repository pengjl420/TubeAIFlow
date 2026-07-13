from sqlmodel import Field, SQLModel

from app.utils.time_utils import utc_now_iso


class SystemSetting(SQLModel, table=True):
    __tablename__ = "system_settings"

    id: int = Field(default=1, primary_key=True)
    config_json: str
    updated_at: str = Field(default_factory=utc_now_iso)
