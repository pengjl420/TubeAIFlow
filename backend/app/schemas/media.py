from pydantic import BaseModel, Field


class AssetImportRequest(BaseModel):
    directory: str = Field(min_length=1)


class SceneAssignmentRequest(BaseModel):
    candidate_id: str = Field(min_length=1)
    trim_start_ms: int = Field(default=0, ge=0)
    trim_end_ms: int | None = Field(default=None, gt=0)
    playback_speed: float = Field(default=1.0, ge=0.5, le=2.0)
    transition: str = Field(default="cut", min_length=1, max_length=30)
