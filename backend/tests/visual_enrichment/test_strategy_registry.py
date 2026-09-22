from __future__ import annotations

import pytest

from app.services.visual_enrichment.models import VisualCandidate, VisualType
from app.services.visual_enrichment.visual_strategy import visual_strategy_registry


def _candidate() -> VisualCandidate:
    return VisualCandidate(
        candidate_id="candidate-1",
        scene_id="scene-1:beat:1",
        parent_scene_id="scene-1",
        start_ms=0,
        end_ms=8_000,
        trigger_ms=0,
        voiceover="A stable visual beat",
        boundary_strength=0.8,
        visualizability=0.8,
        importance=0.8,
        novelty=0.8,
        factual_density=0.5,
        rhetorical_salience=0.7,
        emotion_shift=0.5,
        score=0.8,
        visual_type_hint=VisualType.CONCEPTUAL_ILLUSTRATION,
    )


def test_registered_strategies_publish_capabilities() -> None:
    metadata = {item.id: item for item in visual_strategy_registry.list()}
    assert set(metadata) >= {"curated", "anime_full_coverage"}
    assert metadata["anime_full_coverage"].supports_multiple_beats_per_scene
    assert metadata["anime_full_coverage"].compatible_video_modes == (
        "ai_generated_images",
    )


@pytest.mark.parametrize("strategy_id", ["curated", "anime_full_coverage"])
def test_strategy_plan_is_deterministic(strategy_id: str) -> None:
    strategy = visual_strategy_registry.get(strategy_id)
    kwargs = {
        "project_id": "project",
        "duration_ms": 8_000,
        "candidates": [_candidate()],
        "config": {},
        "provider": None,
    }
    first = strategy.build_plan(**kwargs)
    second = strategy.build_plan(**kwargs)
    assert first.model_dump() == second.model_dump()
    if strategy_id == "anime_full_coverage":
        assert first.visuals[0].scene_id == "scene-1"
        assert first.visuals[0].visual_beat_id == "scene-1:beat:1"


def test_registry_rejects_unknown_or_incompatible_strategy() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        visual_strategy_registry.get("missing")
    with pytest.raises(ValueError, match="incompatible"):
        visual_strategy_registry.resolve_for_video_mode(
            "anime_full_coverage", "ai_landscape_mix"
        )
