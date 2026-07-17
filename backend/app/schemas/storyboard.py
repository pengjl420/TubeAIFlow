from pydantic import BaseModel, Field, field_validator


class SubtitleCueRead(BaseModel):
    id: str
    project_id: str
    source_segment_id: str
    cue_index: int
    start_ms: int
    end_ms: int
    text: str


class StoryboardContent(BaseModel):
    visual_summary: str = Field(min_length=1)
    visual_type: str = Field(min_length=1)
    entities: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    time_period: str = ""
    scene_category: str = Field(min_length=1)
    mood: str = Field(min_length=1)
    shot_preference: str = Field(min_length=1)
    primary_query: str = Field(min_length=1)
    alternative_queries: list[str] = Field(default_factory=list, max_length=5)
    fallback_category: str = Field(min_length=1)
    fallback_mood: str = Field(min_length=1)
    allow_landscape_fallback: bool = False
    must_include: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)

    @field_validator(
        "visual_summary",
        "visual_type",
        "time_period",
        "scene_category",
        "mood",
        "shot_preference",
        "primary_query",
        "fallback_category",
        "fallback_mood",
        mode="before",
    )
    @classmethod
    def normalize_text(cls, value) -> str:
        return str(value or "").strip()

    @field_validator(
        "entities",
        "locations",
        "alternative_queries",
        "must_include",
        "avoid",
        mode="before",
    )
    @classmethod
    def normalize_text_list(cls, value) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("Expected a list")
        return [str(item).strip() for item in value if str(item).strip()]


class VisualSceneRead(BaseModel):
    id: str
    project_id: str
    scene_index: int
    start_ms: int
    end_ms: int
    narration: str
    subtitle_ids: list[str]
    storyboard: StoryboardContent | None = None
    confidence: float | None = None
    status: str


class StoryboardSceneResult(StoryboardContent):
    scene_id: str


class StoryboardBatchResult(BaseModel):
    scenes: list[StoryboardSceneResult]


class SceneGroup(BaseModel):
    subtitle_ids: list[str] = Field(min_length=1)


class SceneGroupingResult(BaseModel):
    groups: list[SceneGroup] = Field(min_length=1)
