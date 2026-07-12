from datetime import datetime

from sqlmodel import Field, SQLModel


class VoiceProfile(SQLModel, table=True):
    __tablename__ = "voice_profiles"

    id: str = Field(primary_key=True)
    name: str
    reference_audio_path: str
    config_json: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
