from sqlmodel import Field, SQLModel

from app.utils.time_utils import utc_now_iso


class VoiceProfile(SQLModel, table=True):
    __tablename__ = "voice_profiles"

    id: str = Field(primary_key=True)
    name: str
    reference_audio_path: str
    config_json: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
