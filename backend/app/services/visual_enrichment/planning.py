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
        priority = "high" if candidate.score >= 0.78 else "medium" if candidate.score >= 0.68 else "low"
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


def _presentation_for(visual_type: VisualType) -> tuple[str, str]:
    if visual_type in {VisualType.CINEMATIC_SCENE, VisualType.CONCEPTUAL_ILLUSTRATION}:
        return "full_bleed", "kenburns_slow_push"
    if visual_type in {VisualType.BAR_CHART, VisualType.LINE_CHART, VisualType.PIE_CHART}:
        return "chart_center", "fade_only"
    if visual_type in {VisualType.FLOW_DIAGRAM, VisualType.ARCHITECTURE_DIAGRAM, VisualType.TIMELINE}:
        return "diagram_center", "fade_only"
    return "center_card", "card_fade_scale"
