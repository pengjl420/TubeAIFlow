from __future__ import annotations

from bisect import bisect_right

from app.services.visual_enrichment.models import SemanticScene, VisualCandidate, VisualType


def score_candidate(
    *,
    boundary_strength: float,
    visualizability: float,
    importance: float,
    novelty: float,
    factual_density: float,
    rhetorical_salience: float,
    emotion_shift: float,
    duplicate_penalty: float = 0,
) -> float:
    value = (
        0.25 * boundary_strength
        + 0.20 * visualizability
        + 0.15 * importance
        + 0.15 * novelty
        + 0.10 * factual_density
        + 0.10 * rhetorical_salience
        + 0.05 * emotion_shift
        - duplicate_penalty
    )
    return round(max(-1, min(1, value)), 6)


def build_candidates(
    scenes: list[SemanticScene], embeddings: list[list[float]] | None = None
) -> list[VisualCandidate]:
    if embeddings is not None and len(embeddings) != len(scenes):
        raise ValueError("Scene embedding count does not match scene count")
    candidates = []
    previous_words: set[str] = set()
    for index, scene in enumerate(scenes, start=1):
        words = set(scene.narration.casefold().split())
        if embeddings is not None and index > 1:
            similarity = sum(
                left * right
                for left, right in zip(embeddings[index - 2], embeddings[index - 1], strict=True)
            )
            duplicate_penalty = round(max(0, similarity) * 0.2, 4)
        else:
            overlap = len(words & previous_words) / max(1, len(words | previous_words))
            duplicate_penalty = round(overlap * 0.2, 4)
        hint = _type_hint(scene.narration)
        score = score_candidate(
            boundary_strength=scene.boundary_strength,
            visualizability=scene.visualizability,
            importance=scene.importance,
            novelty=scene.novelty,
            factual_density=scene.factual_density,
            rhetorical_salience=scene.rhetorical_salience,
            emotion_shift=scene.emotion_shift,
            duplicate_penalty=duplicate_penalty,
        )
        candidates.append(
            VisualCandidate(
                candidate_id=f"candidate_{index:04d}",
                scene_id=scene.scene_id,
                start_ms=scene.start_ms,
                end_ms=scene.end_ms,
                trigger_ms=scene.start_ms,
                voiceover=scene.narration,
                boundary_strength=scene.boundary_strength,
                visualizability=scene.visualizability,
                importance=scene.importance,
                novelty=scene.novelty,
                factual_density=scene.factual_density,
                rhetorical_salience=scene.rhetorical_salience,
                emotion_shift=scene.emotion_shift,
                duplicate_penalty=duplicate_penalty,
                score=score,
                visual_type_hint=hint,
            )
        )
        previous_words = words
    return candidates


def temporal_nms(candidates: list[VisualCandidate], min_gap_ms: int) -> list[VisualCandidate]:
    """Suppress lower-scoring triggers within the configured temporal gap."""
    kept: list[VisualCandidate] = []
    for candidate in sorted(
        candidates, key=lambda item: (-item.score, item.trigger_ms, item.candidate_id)
    ):
        if all(abs(candidate.trigger_ms - other.trigger_ms) >= min_gap_ms for other in kept):
            kept.append(candidate)
    return sorted(kept, key=lambda item: (item.start_ms, item.candidate_id))


def weighted_interval_selection(
    candidates: list[VisualCandidate], *, pre_margin_ms: int = 0, post_gap_ms: int = 0
) -> list[VisualCandidate]:
    """Maximum-score non-overlapping selection with deterministic tie-breaking."""
    ordered = sorted(
        candidates, key=lambda item: (item.end_ms + post_gap_ms, item.start_ms, item.candidate_id)
    )
    ends = [item.end_ms + post_gap_ms for item in ordered]
    predecessors = [
        bisect_right(ends, item.start_ms - pre_margin_ms, hi=index) - 1
        for index, item in enumerate(ordered)
    ]
    totals = [0.0] * (len(ordered) + 1)
    choices: list[list[int]] = [[] for _ in range(len(ordered) + 1)]
    for index, candidate in enumerate(ordered, start=1):
        predecessor = predecessors[index - 1] + 1
        include_total = candidate.score + totals[predecessor]
        exclude_total = totals[index - 1]
        if include_total > exclude_total + 1e-9:
            totals[index] = include_total
            choices[index] = choices[predecessor] + [index - 1]
        else:
            totals[index] = exclude_total
            choices[index] = choices[index - 1]
    return sorted((ordered[index] for index in choices[-1]), key=lambda item: item.start_ms)


def select_candidates(
    candidates: list[VisualCandidate],
    *,
    duration_ms: int,
    threshold: float,
    min_gap_sec: float,
    hard_max_per_minute: float,
) -> list[VisualCandidate]:
    eligible = [candidate for candidate in candidates if candidate.score >= threshold]
    suppressed = temporal_nms(eligible, round(min_gap_sec * 1000))
    selected = weighted_interval_selection(suppressed)
    cap = max(1, int((duration_ms / 60_000) * hard_max_per_minute + 0.9999))
    if len(selected) > cap:
        selected = sorted(selected, key=lambda item: (-item.score, item.start_ms))[:cap]
        selected.sort(key=lambda item: item.start_ms)
    return selected


def _type_hint(text: str) -> VisualType:
    if any(token in text for token in ("流程", "导致", "因此", "因果")):
        return VisualType.FLOW_DIAGRAM
    if any(token in text for token in ("对比", "相比", "另一方面")):
        return VisualType.COMPARISON
    if any(char.isdigit() for char in text):
        return VisualType.FACT_CARD
    if any(token in text for token in ("年", "历史", "过去", "未来")):
        return VisualType.TIMELINE
    return VisualType.CONCEPTUAL_ILLUSTRATION
