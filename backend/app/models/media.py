from sqlmodel import Field, SQLModel

from app.shared.time import utc_now_iso


LIBRARY_ROLE_SEMANTIC = "semantic"
LIBRARY_ROLE_THEMED_FALLBACK = "themed_fallback"
LIBRARY_ROLE_LANDSCAPE_FALLBACK = "landscape_fallback"
LIBRARY_ROLES = {
    LIBRARY_ROLE_SEMANTIC,
    LIBRARY_ROLE_THEMED_FALLBACK,
    LIBRARY_ROLE_LANDSCAPE_FALLBACK,
}


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
    library_role: str = Field(default=LIBRARY_ROLE_SEMANTIC, index=True)
    fallback_category: str = ""
    mood: str = ""
    review_status: str = Field(default="approved", index=True)
    enabled: bool = Field(default=True, index=True)
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
    library_role: str = Field(default=LIBRARY_ROLE_SEMANTIC, index=True)
    fallback_category: str = ""
    mood: str = ""
    status: str = Field(default="ready", index=True)
    technical_json: str = "{}"
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class MediaKeyframe(SQLModel, table=True):
    __tablename__ = "media_keyframes"

    id: str = Field(primary_key=True)
    media_shot_id: str = Field(index=True)
    frame_index: int
    timestamp_ms: int
    path: str
    created_at: str = Field(default_factory=utc_now_iso)


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
    selection_stage: str = Field(default="local_semantic", index=True)
    is_fallback: bool = False
    conflicts_json: str = "[]"
    created_at: str = Field(default_factory=utc_now_iso)


class SceneAssignment(SQLModel, table=True):
    __tablename__ = "scene_assignments"

    id: str = Field(primary_key=True)
    project_id: str = Field(index=True)
    scene_id: str = Field(index=True)
    media_shot_id: str = Field(index=True)
    candidate_id: str | None = Field(default=None, index=True)
    sequence_index: int = Field(default=1, index=True)
    scene_offset_start_ms: int = 0
    scene_offset_end_ms: int | None = None
    trim_start_ms: int = 0
    trim_end_ms: int | None = None
    playback_speed: float = 1.0
    transition: str = "cut"
    manual_confirmed: bool = True
    selection_stage: str = Field(default="manual", index=True)
    selection_reason: str = ""
    is_fallback: bool = False
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class MediaProviderState(SQLModel, table=True):
    __tablename__ = "media_provider_states"

    provider: str = Field(primary_key=True)
    status: str = Field(default="available", index=True)
    rate_limit: int | None = None
    remaining: int | None = None
    reset_at: str | None = None
    last_error: str | None = None
    updated_at: str = Field(default_factory=utc_now_iso)


class MediaQueryCache(SQLModel, table=True):
    __tablename__ = "media_query_cache"

    id: str = Field(primary_key=True)
    provider: str = Field(index=True)
    query: str
    media_type: str = "video"
    response_json: str = "[]"
    expires_at: str = Field(index=True)
    created_at: str = Field(default_factory=utc_now_iso)
