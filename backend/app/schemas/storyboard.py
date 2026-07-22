from pydantic import BaseModel, Field, field_validator


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
    motion_prompt: str = "Subtle natural subject movement. A stable, gentle camera move. Preserve identity and composition."
    scene_type: str = "general"
    importance_score: int = Field(default=5, ge=0, le=10)
    motion_score: int = Field(default=4, ge=0, le=10)
    identity_risk: int = Field(default=5, ge=0, le=10)
    text_density: int = Field(default=0, ge=0, le=10)
    subject_count: int = Field(default=1, ge=0, le=20)

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
        "motion_prompt",
        "scene_type",
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


class StoryboardSceneResult(StoryboardContent):
    scene_id: str


class StoryboardBatchResult(BaseModel):
    scenes: list[StoryboardSceneResult]


class SceneGroup(BaseModel):
    subtitle_ids: list[str] = Field(min_length=1)


class SceneGroupingResult(BaseModel):
    groups: list[SceneGroup] = Field(min_length=1)
