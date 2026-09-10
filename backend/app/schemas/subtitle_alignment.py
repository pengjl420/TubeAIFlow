from typing import Literal

from pydantic import BaseModel, Field, model_validator


Language = Literal["zh", "en"]


class AsrWord(BaseModel):
    text: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    confidence: float = Field(default=1.0, ge=0, le=1)

    @model_validator(mode="after")
    def validate_times(self):
        if self.end_ms <= self.start_ms:
            raise ValueError("ASR word end must be after start")
        return self


class TimedUnit(BaseModel):
    text: str
    display_start: int = Field(ge=0)
    display_end: int = Field(gt=0)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    confidence: float = Field(ge=0, le=1)
    source: Literal["asr_anchor", "interpolated", "heuristic"]


class AlignedCue(BaseModel):
    text: str
    local_start_ms: int = Field(ge=0)
    local_end_ms: int = Field(gt=0)
    confidence: float = Field(ge=0, le=1)
    source_char_start: int = Field(ge=0)
    source_char_end: int = Field(gt=0)
    timing_source: str


class SegmentAlignment(BaseModel):
    segment_id: str
    language: Language
    duration_ms: int = Field(gt=0)
    backend: str
    status: Literal["passed", "needs_review", "failed"]
    confidence: float = Field(ge=0, le=1)
    text_similarity: float = Field(ge=0, le=1)
    anchor_coverage: float = Field(ge=0, le=1)
    units: list[TimedUnit]
    cues: list[AlignedCue]
    error: str | None = None
