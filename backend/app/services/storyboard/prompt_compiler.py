from __future__ import annotations

from app.schemas.storyboard import StoryboardContent, StoryboardVisualBrief


def derive_visual_brief(value: StoryboardContent) -> StoryboardVisualBrief:
    """Create a lossless fallback brief for old providers and persisted projects."""
    return StoryboardVisualBrief(
        subject=value.visual_summary,
        action="show the narrated event or relationship clearly",
        environment=(", ".join(value.locations) or value.scene_category),
        semantic_message=value.visual_summary,
        composition=f"{value.shot_preference} 16:9 composition with one clear focal hierarchy",
        era=value.time_period,
        mood=value.mood,
        must_include=value.must_include,
        must_avoid=value.avoid,
    )


def compile_image_prompt(value: StoryboardContent) -> tuple[str, str]:
    """Compile provider-neutral structured facts into a deterministic image prompt."""
    brief = value.visual_brief or derive_visual_brief(value)
    parts = [
        brief.semantic_message,
        f"Visible subject: {brief.subject}",
        f"Action: {brief.action}",
        f"Environment: {brief.environment}",
        f"Composition: {brief.composition}",
        f"Camera: {brief.camera}",
        f"Mood: {brief.mood}",
    ]
    if brief.era:
        parts.append(f"Period accuracy: {brief.era}")
    if brief.must_include:
        parts.append("Must visibly include: " + ", ".join(brief.must_include))
    parts.extend(
        [
            "cinematic documentary editorial image",
            "photorealistic natural lighting and coherent anatomy",
            "16:9 landscape; keep the lower 18 percent visually quiet for subtitles",
        ]
    )
    negative_values = [
        "watermark",
        "logo",
        "random text",
        "copyrighted characters",
        *brief.must_avoid,
        *value.avoid,
    ]
    negative = ", ".join(_deduplicate(negative_values))
    return ". ".join(item.strip(" .") for item in parts if item.strip()), negative


def _deduplicate(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for item in values:
        value = str(item or "").strip()
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result
