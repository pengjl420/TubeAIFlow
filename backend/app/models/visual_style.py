from sqlmodel import Field, SQLModel

from app.shared.time import utc_now_iso


class VisualStyleProfile(SQLModel, table=True):
    __tablename__ = "visual_style_profiles"

    id: str = Field(primary_key=True)
    name: str
    description: str = ""
    tags_json: str = "[]"
    status: str = Field(default="draft", index=True)
    current_revision_id: str | None = Field(default=None, index=True)
    draft_revision_id: str | None = Field(default=None, index=True)
    cover_image_path: str | None = None
    builtin_key: str | None = Field(default=None, index=True)
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class VisualStyleRevision(SQLModel, table=True):
    __tablename__ = "visual_style_revisions"

    id: str = Field(primary_key=True)
    style_profile_id: str = Field(index=True)
    version: int
    status: str = Field(default="draft", index=True)
    style_prompt: str
    negative_prompt: str = ""
    continuity_rules_json: str = "[]"
    composition_rules_json: str = "[]"
    motion_preset_json: str = "{}"
    source: str = "manual"
    parent_revision_id: str | None = None
    content_hash: str = Field(index=True)
    optimization_metadata_json: str = "{}"
    created_at: str = Field(default_factory=utc_now_iso)
    published_at: str | None = None


class StyleTestRun(SQLModel, table=True):
    __tablename__ = "style_test_runs"

    id: str = Field(primary_key=True)
    client_request_id: str | None = Field(default=None, index=True)
    style_revision_id: str = Field(index=True)
    status: str = Field(default="queued", index=True)
    candidate_count: int = 1
    scene_description: str
    compiled_prompt: str = ""
    compiled_negative_prompt: str = ""
    provider_id: str = "image.seedream_5"
    model_id: str = "doubao-seedream-5-0-pro-260628"
    output_json: str = "[]"
    generation_seconds: float | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str | None = Field(default_factory=utc_now_iso)
    started_at: str | None = None
    finished_at: str | None = None


class StyleAsset(SQLModel, table=True):
    __tablename__ = "style_assets"

    id: str = Field(primary_key=True)
    style_profile_id: str = Field(index=True)
    style_revision_id: str = Field(index=True)
    source_type: str = Field(index=True)
    source_project_id: str | None = Field(default=None, index=True)
    source_scene_id: str | None = Field(default=None, index=True)
    source_test_run_id: str | None = Field(default=None, index=True)
    source_variant_id: str | None = Field(default=None, index=True)
    path: str
    file_hash: str = Field(index=True)
    perceptual_hash: str = Field(default="", index=True)
    prompt: str = ""
    negative_prompt: str = ""
    query_text: str = ""
    entities_json: str = "[]"
    locations_json: str = "[]"
    mood: str = ""
    fact_risk: str = "low"
    width: int = 0
    height: int = 0
    provider_id: str = ""
    model_id: str = ""
    status: str = Field(default="unreviewed", index=True)
    text_fingerprint_json: str = "[]"
    embedding_model_id: str = "local-text-fingerprint-v1"
    usage_count: int = 0
    last_used_at: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class StyleAssetMatch(SQLModel, table=True):
    __tablename__ = "style_asset_matches"

    id: str = Field(primary_key=True)
    project_id: str = Field(index=True)
    scene_id: str = Field(index=True)
    style_asset_id: str = Field(index=True)
    query_text: str
    semantic_score: float
    decision: str = Field(index=True)
    materialized_path: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
