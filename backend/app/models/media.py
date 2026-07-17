from sqlmodel import Field, SQLModel

from app.shared.time import utc_now_iso


class MediaFile(SQLModel, table=True):
    __tablename__ = "media_files"

    id: str = Field(primary_key=True)
    provider: str = Field(default="local", index=True)
    provider_asset_id: str | None = Field(default=None, index=True)
    path: str
    filename: str
    media_type: str = Field(index=True)
    file_hash: str = Field(index=True)
    size_bytes: int = 0
    duration_ms: int | None = None
    width: int | None = None
    height: int | None = None
    status: str = Field(default="ready", index=True)
    metadata_json: str = "{}"
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class MediaShot(SQLModel, table=True):
    __tablename__ = "media_shots"

    id: str = Field(primary_key=True)
    media_file_id: str = Field(index=True)
    shot_index: int
    start_ms: int = 0
    end_ms: int | None = None
    description: str = ""
    tags_json: str = "[]"
    thumbnail_path: str | None = None
    vector_id: int | None = None
    status: str = Field(default="ready", index=True)
    technical_json: str = "{}"
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class SceneCandidate(SQLModel, table=True):
    __tablename__ = "scene_candidates"

    id: str = Field(primary_key=True)
    project_id: str = Field(index=True)
    scene_id: str = Field(index=True)
    media_shot_id: str = Field(index=True)
    source: str = "local"
    query: str = ""
    semantic_score: float = 0
    text_score: float = 0
    tag_score: float = 0
    technical_score: float = 0
    total_score: float = 0
    status: str = Field(default="LOW_RELEVANCE", index=True)
    conflicts_json: str = "[]"
    created_at: str = Field(default_factory=utc_now_iso)


class SceneAssignment(SQLModel, table=True):
    __tablename__ = "scene_assignments"

    id: str = Field(primary_key=True)
    project_id: str = Field(index=True)
    scene_id: str = Field(index=True)
    media_shot_id: str = Field(index=True)
    candidate_id: str | None = Field(default=None, index=True)
    trim_start_ms: int = 0
    trim_end_ms: int | None = None
    playback_speed: float = 1.0
    transition: str = "cut"
    manual_confirmed: bool = True
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
