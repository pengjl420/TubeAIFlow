from __future__ import annotations

import re

import json
from pydantic import BaseModel, Field

from app.services.visual_enrichment.models import CanonicalSegment, Chapter, SemanticScene
from app.services.visual_enrichment.providers import LLMProvider


DISCOURSE_MARKERS = ("但是", "另一方面", "最后", "关键在于", "因此", "然而", "与此同时")
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?%?")


class ChapterAnalysis(BaseModel):
    chapter_title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    main_claims: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    narrative_mode: str = "explanation"
    emotion_curve: str = "steady"


def build_chapters(
    segments: list[CanonicalSegment], provider: LLMProvider, chunk_minutes: tuple[int, int] = (2, 4)
) -> list[Chapter]:
    max_chunk_ms = max(chunk_minutes) * 60_000
    groups: list[list[CanonicalSegment]] = []
    current: list[CanonicalSegment] = []
    for segment in segments:
        if current and segment.end_ms - current[0].start_ms > max_chunk_ms:
            groups.append(current)
            current = []
        current.append(segment)
    if current:
        groups.append(current)
    chapters = []
    previous_summary = ""
    for index, group in enumerate(groups, start=1):
        text = " ".join(item.subtitle_text.replace("\n", " ") for item in group)
        raw = provider.generate_json(
            json.dumps(
                {
                    "instruction": (
                        "Analyze this transcript chunk as a documentary chapter. Do not select images. "
                        "Return the chapter title, concise summary, main claims, visible entities, "
                        "narrative mode, and emotion curve."
                    ),
                    "previous_summary": previous_summary,
                    "start_ms": group[0].start_ms,
                    "end_ms": group[-1].end_ms,
                    "text": text,
                },
                ensure_ascii=False,
            ),
            ChapterAnalysis.model_json_schema(),
            {"temperature": 0.3, "top_p": 0.8, "max_tokens": 2048},
        )
        analysis = ChapterAnalysis.model_validate(raw)
        chapters.append(
            Chapter(
                chapter_id=f"chapter_{index:04d}",
                start_ms=group[0].start_ms,
                end_ms=group[-1].end_ms,
                title=analysis.chapter_title,
                summary=analysis.summary,
                main_claims=analysis.main_claims,
                entities=analysis.entities,
                narrative_mode=analysis.narrative_mode,
                emotion_curve=analysis.emotion_curve,
            )
        )
        previous_summary = analysis.summary
    return chapters


def segment_scenes(
    segments: list[CanonicalSegment],
    chapters: list[Chapter],
    *,
    target_scene_sec: tuple[int, int] = (8, 18),
    min_scene_sec: int = 5,
    max_scene_sec: int = 30,
) -> list[SemanticScene]:
    if not segments:
        return []
    target_ms = target_scene_sec[0] * 1000
    min_ms = min_scene_sec * 1000
    max_ms = max_scene_sec * 1000
    groups: list[list[CanonicalSegment]] = []
    current: list[CanonicalSegment] = []
    for segment in segments:
        proposed_duration = segment.end_ms - (current[0].start_ms if current else segment.start_ms)
        marker_boundary = any(marker in segment.subtitle_text for marker in DISCOURSE_MARKERS)
        if current and proposed_duration > max_ms:
            groups.append(current)
            current = []
        current.append(segment)
        duration = current[-1].end_ms - current[0].start_ms
        if duration >= target_ms or (duration >= min_ms and marker_boundary):
            groups.append(current)
            current = []
    if current:
        if groups and current[-1].end_ms - current[0].start_ms < min_ms:
            groups[-1].extend(current)
        else:
            groups.append(current)

    scenes = []
    for index, group in enumerate(groups, start=1):
        narration = " ".join(item.subtitle_text.replace("\n", " ") for item in group)
        chapter_id = next(
            (
                chapter.chapter_id
                for chapter in chapters
                if chapter.start_ms <= group[0].start_ms < chapter.end_ms
            ),
            chapters[-1].chapter_id,
        )
        has_number = bool(NUMBER_RE.search(narration))
        has_marker = any(marker in narration for marker in DISCOURSE_MARKERS)
        scenes.append(
            SemanticScene(
                scene_id=f"scene_{index:04d}",
                chapter_id=chapter_id,
                start_ms=group[0].start_ms,
                end_ms=group[-1].end_ms,
                segment_ids=[item.segment_id for item in group],
                narration=narration,
                boundary_strength=0.82 if has_marker else 0.7,
                visualizability=0.82 if has_number else 0.74,
                importance=0.78 if has_marker or has_number else 0.7,
                novelty=max(0.55, 0.82 - index * 0.01),
                factual_density=0.86 if has_number else 0.55,
                rhetorical_salience=0.8 if has_marker else 0.62,
                emotion_shift=0.65 if any(mark in narration for mark in "!?！？") else 0.45,
            )
        )
    return scenes
