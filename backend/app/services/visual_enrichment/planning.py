from __future__ import annotations

import hashlib
import json
import re

from pydantic import BaseModel

from app.services.visual_enrichment.models import (
    GenerationSpec,
    OverlayItem,
    OverlayTimeline,
    Renderer,
    VisualBrief,
    VisualCandidate,
    VisualPlan,
    VisualPlanItem,
    VisualType,
)
from app.services.visual_enrichment.providers import LLMProvider


HIGH_RISK_RE = re.compile(r"\d+(?:\.\d+)?%?|医疗|法律|金融|日期|统计|收入|成本")

DEFAULT_ANIME_STYLE_PROMPT = (
    "Original non-photorealistic 2D animated documentary illustration, clean expressive line art, "
    "controlled cel shading, consistent character proportions and facial design, cohesive navy teal "
    "and warm amber color palette, soft cinematic lighting, detailed but uncluttered background, "
    "professional widescreen composition. Preserve the same art direction across every scene."
)
DEFAULT_ANIME_NEGATIVE_PROMPT = (
    "photorealistic, 3D render, live action, inconsistent character design, random costume changes, "
    "watermark, logo, random text, copyrighted character, imitation of a named living artist"
)


class VisualPlanningDecision(BaseModel):
    visual_type: VisualType
    brief: VisualBrief


def renderer_for(visual_type: VisualType) -> Renderer:
    if visual_type in {VisualType.CINEMATIC_SCENE, VisualType.CONCEPTUAL_ILLUSTRATION}:
        return Renderer.FLUX
    if visual_type in {VisualType.BAR_CHART, VisualType.LINE_CHART, VisualType.PIE_CHART}:
        return Renderer.MATPLOTLIB
    if visual_type in {
        VisualType.COMPARISON,
        VisualType.FLOW_DIAGRAM,
        VisualType.ARCHITECTURE_DIAGRAM,
        VisualType.TIMELINE,
        VisualType.MAP,
    }:
        return Renderer.SVG
    if visual_type in {
        VisualType.FACT_CARD,
        VisualType.QUOTE_CARD,
        VisualType.KEYWORD_CARD,
        VisualType.LIST_CARD,
        VisualType.OBJECT_CUTOUT,
    }:
        return Renderer.PILLOW
    return Renderer.NONE


def fact_risk_for(text: str) -> str:
    return "high" if HIGH_RISK_RE.search(text) else "low"


def build_visual_plan(
    project_id: str,
    duration_ms: int,
    selected: list[VisualCandidate],
    *,
    width: int = 1344,
    height: int = 768,
    subtitle_safe_zone: float = 0.18,
    candidates_normal: int = 2,
    candidates_high: int = 3,
    provider: LLMProvider | None = None,
) -> VisualPlan:
    visuals = []
    for index, candidate in enumerate(selected, start=1):
        decision = _planning_decision(candidate, provider)
        visual_type = decision.visual_type
        risk = fact_risk_for(candidate.voiceover)
        renderer = renderer_for(visual_type)
        if risk == "high" and renderer == Renderer.FLUX:
            visual_type, renderer = VisualType.FACT_CARD, Renderer.PILLOW
        priority = (
            "high" if candidate.score >= 0.78 else "medium" if candidate.score >= 0.68 else "low"
        )
        visual_id = f"vis_{index:04d}"
        seed = int(hashlib.sha256(f"{project_id}:{visual_id}".encode()).hexdigest()[:8], 16)
        brief = decision.brief
        prompt = _build_prompt(candidate.voiceover, brief, subtitle_safe_zone)
        layout, animation = _presentation_for(visual_type)
        visuals.append(
            VisualPlanItem(
                visual_id=visual_id,
                scene_id=candidate.scene_id,
                start_ms=candidate.start_ms,
                end_ms=candidate.end_ms,
                trigger_ms=candidate.trigger_ms,
                priority=priority,
                voiceover=candidate.voiceover,
                core_claim=candidate.voiceover,
                visual_purpose="Explain or emphasize this selected semantic beat.",
                visual_type=visual_type,
                renderer=renderer,
                fact_risk=risk,
                visual_brief=brief,
                prompt=prompt,
                negative_prompt="No watermark. No logo. No random text. No copyrighted characters.",
                generation=GenerationSpec(
                    width=width,
                    height=height,
                    candidates=candidates_high if priority == "high" else candidates_normal,
                    seed_base=seed,
                ),
                layout=layout,
                animation=animation,
                subtitle_safe_zone=subtitle_safe_zone,
            )
        )
    return VisualPlan(project_id=project_id, duration_ms=duration_ms, visuals=visuals)


def build_anime_visual_plan(
    project_id: str,
    duration_ms: int,
    candidates: list[VisualCandidate],
    *,
    width: int = 1344,
    height: int = 768,
    subtitle_safe_zone: float = 0.18,
    candidates_per_scene: int = 1,
    style_prompt: str = DEFAULT_ANIME_STYLE_PROMPT,
    negative_style_prompt: str = DEFAULT_ANIME_NEGATIVE_PROMPT,
    provider: LLMProvider | None = None,
) -> VisualPlan:
    """Build one styled master illustration for every semantic scene.

    Unlike the curated documentary strategy, callers pass the complete ordered
    candidate list.  No score threshold, temporal suppression, or per-minute cap
    is applied.  Scenes are still semantic units rather than fixed-time slices so
    a sentence is not cut merely to satisfy a visual cadence.
    """
    visuals = []
    for index, candidate in enumerate(candidates, start=1):
        decision = _anime_planning_decision(candidate, provider)
        visual_id = f"anime_{index:04d}"
        seed = int(hashlib.sha256(f"{project_id}:{visual_id}".encode()).hexdigest()[:8], 16)
        context_before = candidates[index - 2].voiceover if index > 1 else ""
        context_after = candidates[index].voiceover if index < len(candidates) else ""
        brief = decision.brief
        prompt = _build_anime_prompt(
            candidate.voiceover,
            brief,
            style_prompt,
            subtitle_safe_zone,
            context_before=context_before,
            context_after=context_after,
        )
        visuals.append(
            VisualPlanItem(
                visual_id=visual_id,
                scene_id=candidate.parent_scene_id or candidate.scene_id,
                visual_beat_id=candidate.scene_id,
                start_ms=candidate.start_ms,
                end_ms=candidate.end_ms,
                trigger_ms=candidate.trigger_ms,
                priority="high" if candidate.score >= 0.78 else "medium",
                voiceover=candidate.voiceover,
                context_before=context_before,
                context_after=context_after,
                core_claim=candidate.voiceover,
                visual_purpose="Cover this complete narration beat with a coherent 2D animated scene.",
                visual_type=VisualType.CONCEPTUAL_ILLUSTRATION,
                renderer=Renderer.FLUX,
                fact_risk=fact_risk_for(candidate.voiceover),
                visual_brief=brief,
                prompt=prompt,
                negative_prompt=negative_style_prompt or DEFAULT_ANIME_NEGATIVE_PROMPT,
                generation=GenerationSpec(
                    width=width,
                    height=height,
                    candidates=candidates_per_scene,
                    seed_base=seed,
                ),
                layout="full_bleed",
                animation="anime_master_kenburns",
                subtitle_safe_zone=subtitle_safe_zone,
            )
        )
    return VisualPlan(
        project_id=project_id,
        duration_ms=duration_ms,
        strategy="anime_full_coverage",
        strategy_version="2",
        visuals=visuals,
    )


def _planning_decision(
    candidate: VisualCandidate, provider: LLMProvider | None
) -> VisualPlanningDecision:
    fallback = VisualPlanningDecision(
        visual_type=candidate.visual_type_hint,
        brief=VisualBrief(
            subject=_brief_subject(candidate.voiceover),
            action="communicates the narrated claim through one clear visual relationship",
            environment="clean documentary editorial setting",
            semantic_message=candidate.voiceover,
            composition="wide composition with a single focal hierarchy",
            must_avoid=["visible logos", "watermark", "random text"],
        ),
    )
    if provider is None:
        return fallback
    try:
        raw = provider.generate_json(
            json.dumps(
                {
                    "instruction": (
                        "Plan one concrete documentary visual. Select the visual type that best "
                        "communicates the claim; do not merely restate the narration. The brief must "
                        "describe visible subject, action, environment and composition. Preserve "
                        "factual uncertainty and avoid invented identities, logos or quotations."
                    ),
                    "voiceover": candidate.voiceover,
                    "timing": {"start_ms": candidate.start_ms, "end_ms": candidate.end_ms},
                    "suggested_type": candidate.visual_type_hint.value,
                },
                ensure_ascii=False,
            ),
            VisualPlanningDecision.model_json_schema(),
            {"temperature": 0.25, "top_p": 0.8, "max_tokens": 1200},
        )
        return VisualPlanningDecision.model_validate(raw)
    except (ValueError, TypeError, KeyError):
        return fallback


def _anime_planning_decision(
    candidate: VisualCandidate, provider: LLMProvider | None
) -> VisualPlanningDecision:
    fallback = VisualPlanningDecision(
        visual_type=VisualType.CONCEPTUAL_ILLUSTRATION,
        brief=VisualBrief(
            subject=_brief_subject(candidate.voiceover),
            action="visually enacts the narrated idea through one clear story moment",
            environment="a concrete setting implied by the narration",
            semantic_message=candidate.voiceover,
            composition="wide story composition with a clear foreground subject and readable depth",
            mood="cohesive animated documentary",
            must_avoid=["visible logos", "watermark", "random text", "copyrighted characters"],
        ),
    )
    if provider is None:
        return fallback
    try:
        raw = provider.generate_json(
            json.dumps(
                {
                    "instruction": (
                        "Plan one original non-photorealistic 2D animated scene that directly "
                        "visualizes this narration beat. Describe a concrete subject, visible action, "
                        "environment, emotion and widescreen composition. Keep factual uncertainty, "
                        "do not invent quotations or identities, and do not request visible text, "
                        "logos, copyrighted characters, or the style of a named living artist."
                    ),
                    "voiceover": candidate.voiceover,
                    "timing": {"start_ms": candidate.start_ms, "end_ms": candidate.end_ms},
                    "suggested_type": VisualType.CONCEPTUAL_ILLUSTRATION.value,
                },
                ensure_ascii=False,
            ),
            VisualPlanningDecision.model_json_schema(),
            {"temperature": 0.2, "top_p": 0.8, "max_tokens": 1200},
        )
        decision = VisualPlanningDecision.model_validate(raw)
        decision.visual_type = VisualType.CONCEPTUAL_ILLUSTRATION
        return decision
    except (ValueError, TypeError, KeyError):
        return fallback


def build_overlay_timeline(plan: VisualPlan) -> OverlayTimeline:
    return OverlayTimeline(
        project_id=plan.project_id,
        duration_ms=plan.duration_ms,
        overlays=[
            OverlayItem(
                visual_id=visual.visual_id,
                start_ms=visual.start_ms,
                end_ms=visual.end_ms,
                asset_path=f"work/05_assets/approved/{visual.visual_id}.png",
                layout=visual.layout,
                animation=visual.animation,
                subtitle_safe_zone=visual.subtitle_safe_zone,
            )
            for visual in plan.visuals
        ],
    )


def _brief_subject(text: str) -> str:
    compact = " ".join(text.split())
    return compact[:80] or "the central narrated concept"


def _build_prompt(core_claim: str, brief: VisualBrief, safe_zone: float) -> str:
    return (
        "Create a cinematic editorial visual for a narrated educational YouTube video.\n\n"
        f"CORE CLAIM:\n{core_claim}\n\n"
        f"THE IMAGE MUST COMMUNICATE:\n{brief.semantic_message}\n\n"
        f"SUBJECT:\n{brief.subject}\n\nACTION:\n{brief.action}\n\n"
        f"ENVIRONMENT:\n{brief.environment}\n\nCOMPOSITION:\n16:9 landscape. "
        f"{brief.composition}. Keep the bottom {safe_zone:.0%} visually quiet for subtitles.\n\n"
        "SAFETY:\nNo visible brand logos. No watermark. No random text. "
        "No copyrighted characters. Do not imitate a named living artist."
    )


def _build_anime_prompt(
    core_claim: str,
    brief: VisualBrief,
    style_prompt: str,
    safe_zone: float,
    *,
    context_before: str = "",
    context_after: str = "",
) -> str:
    return (
        f"SERIES ART DIRECTION — apply exactly to this scene:\n{style_prompt}\n\n"
        f"CURRENT NARRATION BEAT:\n{core_claim}\n\n"
        f"VISIBLE STORY MOMENT:\nSubject: {brief.subject}\nAction: {brief.action}\n"
        f"Environment: {brief.environment}\nMood: {brief.mood}\n"
        f"Semantic message: {brief.semantic_message}\n\n"
        f"CONTINUITY CONTEXT — use only to preserve recurring people, objects and setting; "
        f"do not illustrate unrelated details:\nPrevious: {context_before or 'none'}\n"
        f"Next: {context_after or 'none'}\n\n"
        f"COMPOSITION:\n16:9 landscape. {brief.composition}. Keep the bottom "
        f"{safe_zone:.0%} visually quiet for subtitles. One decisive focal hierarchy.\n\n"
        "SAFETY:\nNo visible text, logo, watermark or copyrighted character. "
        "Do not imitate a named living artist."
    )


def _presentation_for(visual_type: VisualType) -> tuple[str, str]:
    if visual_type in {VisualType.CINEMATIC_SCENE, VisualType.CONCEPTUAL_ILLUSTRATION}:
        return "full_bleed", "kenburns_slow_push"
    if visual_type in {VisualType.BAR_CHART, VisualType.LINE_CHART, VisualType.PIE_CHART}:
        return "chart_center", "fade_only"
    if visual_type in {
        VisualType.FLOW_DIAGRAM,
        VisualType.ARCHITECTURE_DIAGRAM,
        VisualType.TIMELINE,
    }:
        return "diagram_center", "fade_only"
    return "center_card", "card_fade_scale"
