import unittest

from app.services.visual_enrichment.models import VisualCandidate, VisualType
from app.services.visual_enrichment.selection import (
    score_candidate,
    temporal_nms,
    weighted_interval_selection,
)
from app.services.visual_enrichment.planning import build_anime_visual_plan


def candidate(candidate_id: str, start: int, end: int, score: float) -> VisualCandidate:
    return VisualCandidate(
        candidate_id=candidate_id,
        scene_id=candidate_id,
        start_ms=start,
        end_ms=end,
        trigger_ms=start,
        voiceover=candidate_id,
        boundary_strength=score,
        visualizability=score,
        importance=score,
        novelty=score,
        factual_density=score,
        rhetorical_salience=score,
        emotion_shift=score,
        score=score,
        visual_type_hint=VisualType.CONCEPTUAL_ILLUSTRATION,
    )


class SelectionTests(unittest.TestCase):
    def test_score_uses_documented_weights_and_penalty(self) -> None:
        self.assertEqual(
            score_candidate(
                boundary_strength=1,
                visualizability=1,
                importance=1,
                novelty=1,
                factual_density=1,
                rhetorical_salience=1,
                emotion_shift=1,
                duplicate_penalty=0.2,
            ),
            0.8,
        )

    def test_temporal_nms_keeps_highest_score(self) -> None:
        selected = temporal_nms(
            [candidate("low", 0, 3000, 0.6), candidate("high", 2000, 5000, 0.9)],
            min_gap_ms=5000,
        )
        self.assertEqual([item.candidate_id for item in selected], ["high"])

    def test_weighted_interval_can_beat_single_high_candidate(self) -> None:
        selected = weighted_interval_selection(
            [
                candidate("wide", 0, 10_000, 0.9),
                candidate("left", 0, 5_000, 0.6),
                candidate("right", 5_000, 10_000, 0.6),
            ]
        )
        self.assertEqual([item.candidate_id for item in selected], ["left", "right"])

    def test_anime_plan_covers_every_candidate_without_curated_limits(self) -> None:
        candidates = [
            candidate("first", 0, 8_000, 0.2),
            candidate("second", 8_000, 16_000, 0.3),
            candidate("third", 16_000, 24_000, 0.4),
        ]

        plan = build_anime_visual_plan(
            "project",
            24_000,
            candidates,
            candidates_per_scene=1,
            style_prompt="consistent original 2D style",
        )

        self.assertEqual(plan.strategy, "anime_full_coverage")
        self.assertEqual([item.scene_id for item in plan.visuals], ["first", "second", "third"])
        self.assertTrue(all(item.renderer.value == "flux2_klein_4b" for item in plan.visuals))
        self.assertTrue(all(item.generation.candidates == 1 for item in plan.visuals))
        self.assertTrue(all("consistent original 2D style" in item.prompt for item in plan.visuals))
