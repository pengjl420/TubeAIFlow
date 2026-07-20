from sqlmodel import Field, SQLModel

from app.shared.time import utc_now_iso


class SubtitleCue(SQLModel, table=True):
    __tablename__ = "subtitle_cues"

    id: str = Field(primary_key=True)
    project_id: str = Field(index=True)
    source_segment_id: str = Field(index=True)
    cue_index: int
    start_ms: int
    end_ms: int
    text: str
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class VisualScene(SQLModel, table=True):
    __tablename__ = "visual_scenes"

    id: str = Field(primary_key=True)
    project_id: str = Field(index=True)
    scene_index: int
    start_ms: int
    end_ms: int
    narration: str
    subtitle_ids_json: str = "[]"
    storyboard_json: str | None = None
    confidence: float | None = None
    status: str = "draft"
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
