from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TranscriptSpan(StrictModel):
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_order(self):
        if self.char_end < self.char_start:
            raise ValueError("char_end must be greater than or equal to char_start")
        return self


class CanonicalSegment(StrictModel):
    segment_id: str = Field(min_length=1)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    subtitle_text: str = Field(min_length=1)
    normalized_text: str = Field(min_length=1)
    transcript_span: TranscriptSpan

    @model_validator(mode="after")
    def validate_times(self):
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class Chapter(StrictModel):
    chapter_id: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    title: str
    summary: str
    main_claims: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    narrative_mode: str = "explanation"
    emotion_curve: str = "steady"


class SemanticScene(StrictModel):
    scene_id: str
    chapter_id: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    segment_ids: list[str] = Field(min_length=1)
    narration: str = Field(min_length=1)
    boundary_strength: float = Field(ge=0, le=1)
    visualizability: float = Field(ge=0, le=1)
    importance: float = Field(ge=0, le=1)
    novelty: float = Field(ge=0, le=1)
    factual_density: float = Field(ge=0, le=1)
    rhetorical_salience: float = Field(ge=0, le=1)
    emotion_shift: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_times(self):
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class VisualType(StrEnum):
    CINEMATIC_SCENE = "cinematic_scene"
    CONCEPTUAL_ILLUSTRATION = "conceptual_illustration"
    COMPARISON = "comparison"
    FLOW_DIAGRAM = "flow_diagram"
    ARCHITECTURE_DIAGRAM = "architecture_diagram"
    TIMELINE = "timeline"
    BAR_CHART = "bar_chart"
    LINE_CHART = "line_chart"
    PIE_CHART = "pie_chart"
    MAP = "map"
    FACT_CARD = "fact_card"
    QUOTE_CARD = "quote_card"
    KEYWORD_CARD = "keyword_card"
    LIST_CARD = "list_card"
    OBJECT_CUTOUT = "object_cutout"
    NONE = "none"


class Renderer(StrEnum):
    FLUX = "flux2_klein_4b"
    SVG = "svg"
    MATPLOTLIB = "matplotlib"
    PILLOW = "pillow"
    NONE = "none"


class VisualCandidate(StrictModel):
    candidate_id: str
    scene_id: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    trigger_ms: int = Field(ge=0)
    voiceover: str
    boundary_strength: float = Field(ge=0, le=1)
    visualizability: float = Field(ge=0, le=1)
    importance: float = Field(ge=0, le=1)
    novelty: float = Field(ge=0, le=1)
    factual_density: float = Field(ge=0, le=1)
    rhetorical_salience: float = Field(ge=0, le=1)
    emotion_shift: float = Field(ge=0, le=1)
    duplicate_penalty: float = Field(default=0, ge=0, le=1)
    score: float = Field(ge=-1, le=1)
    visual_type_hint: VisualType


class VisualBrief(StrictModel):
    subject: str
    action: str
    environment: str
    semantic_message: str
    composition: str
    mood: str = "documentary"
    must_include: list[str] = Field(default_factory=list)
    must_avoid: list[str] = Field(default_factory=list)


class GenerationSpec(StrictModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    candidates: int = Field(ge=1, le=4)
    seed_base: int = Field(ge=0)


class VisualPlanItem(StrictModel):
    visual_id: str
    scene_id: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    trigger_ms: int = Field(ge=0)
    priority: str = Field(pattern="^(low|medium|high)$")
    voiceover: str
    context_before: str = ""
    context_after: str = ""
    core_claim: str
    visual_purpose: str
    visual_type: VisualType
    renderer: Renderer
    fact_risk: str = Field(pattern="^(none|low|medium|high)$")
    visual_brief: VisualBrief
    prompt: str
    negative_prompt: str
    generation: GenerationSpec
    layout: str
    animation: str
    subtitle_safe_zone: float = Field(ge=0, le=0.4)


class VisualPlan(StrictModel):
    project_id: str = Field(min_length=1)
    duration_ms: int = Field(gt=0)
    visuals: list[VisualPlanItem]


class OverlayItem(StrictModel):
    visual_id: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    asset_path: str
    layout: str
    animation: str
    subtitle_safe_zone: float = Field(ge=0, le=0.4)


class OverlayTimeline(StrictModel):
    project_id: str
    duration_ms: int = Field(gt=0)
    overlays: list[OverlayItem]


class ProviderGeneration(StrictModel):
    provider: str
    model: str
    payload: dict[str, Any]
