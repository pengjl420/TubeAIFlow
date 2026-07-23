from sqlmodel import Field, SQLModel

from app.shared.time import utc_now_iso


LIBRARY_ROLE_PROJECT_GENERATED = "project_generated"
LIBRARY_ROLE_LOCAL_LANDSCAPE = "local_landscape"


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
    library_role: str = Field(default=LIBRARY_ROLE_PROJECT_GENERATED, index=True)
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
    library_role: str = Field(default=LIBRARY_ROLE_PROJECT_GENERATED, index=True)
    status: str = Field(default="ready", index=True)
    technical_json: str = "{}"
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class SceneAssignment(SQLModel, table=True):
    __tablename__ = "scene_assignments"

    id: str = Field(primary_key=True)
    project_id: str = Field(index=True)
    scene_id: str = Field(index=True)
    media_shot_id: str = Field(index=True)
    sequence_index: int = Field(default=1, index=True)
    scene_offset_start_ms: int = 0
    scene_offset_end_ms: int | None = None
    trim_start_ms: int = 0
    trim_end_ms: int | None = None
    playback_speed: float = 1.0
    display_duration_ms: int | None = None
    render_mode: str = "auto"
    motion_type: str = "auto"
    zoom_start: float = 1.0
    zoom_end: float = 1.06
    pan_direction: str = "center"
    crop_anchor: str = "center"
    transition: str = "cut"
    selection_stage: str = Field(default="generated_image", index=True)
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class GeneratedImageVariant(SQLModel, table=True):
    __tablename__ = "generated_image_variants"

    id: str = Field(primary_key=True)
    project_id: str = Field(index=True)
    scene_id: str = Field(index=True)
    variant_index: int
    path: str
    prompt: str
    negative_prompt: str = ""
    model_path: str
    model_name: str = ""
    workflow_version: str = "sdxl_single_file_v1"
    input_signature: str = Field(index=True)
    seed: int
    width: int
    height: int
    steps: int
    guidance_scale: float
    status: str = Field(default="pending", index=True)
    generation_seconds: float | None = None
    error_message: str | None = None
    media_file_id: str | None = Field(default=None, index=True)
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
