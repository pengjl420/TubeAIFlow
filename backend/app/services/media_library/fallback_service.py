import hashlib
import random

from sqlmodel import Session, select

from app.config import get_settings
from app.models.media import (
    LIBRARY_ROLE_LANDSCAPE_FALLBACK,
    MediaShot,
    SceneAssignment,
)
from app.models.project import Project
from app.models.storyboard import VisualScene
from app.schemas.media import SceneAssignmentRequest
from app.services.rendering import timeline_composer


AUTO_REASON_PREFIX = "系统自动兜底"


def auto_fill_scene(
    session: Session,
    project: Project,
    scene: VisualScene,
    candidates: list[dict],
    review_required: bool | None = None,
) -> dict:
    settings = get_settings()
    coverage = timeline_composer.scene_coverage(session, scene)
    if not settings.auto_fallback_enabled or coverage["complete"]:
        return _result([], coverage, False)

    eligible = [
        item
        for item in candidates
        if item.get("status") == "QUALIFIED"
        and item.get("is_fallback")
        and (
            item.get("selection_stage") != LIBRARY_ROLE_LANDSCAPE_FALLBACK
            or settings.auto_landscape_fallback_enabled
        )
    ]
    if not eligible:
        return _result([], coverage, False)

    used_shot_ids, used_media_ids = _used_project_assets(session, project.id)
    selected = []
    threshold_exceeded = False
    last_media_id = _last_scene_media_id(session, coverage["assignments"])
    existing_consecutive = _trailing_auto_fallback_count(coverage["assignments"])
    available_slots = max(
        0, settings.auto_fallback_max_consecutive_shots - existing_consecutive
    )
    for candidate in _weighted_order(project.id, scene.id, eligible):
        if len(selected) >= available_slots:
            break
        if candidate["media_shot_id"] in used_shot_ids:
            continue
        media_id = candidate["media"]["id"]
        if media_id == last_media_id or media_id in used_media_ids:
            continue

        from app.services.media_library import retrieval_service

        assignment_data = retrieval_service.assign_candidate(
            session,
            project,
            scene.id,
            SceneAssignmentRequest(candidate_id=candidate["id"], append=True),
        )
        assignment = session.get(SceneAssignment, assignment_data["id"])
        if not assignment:
            raise ValueError("自动兜底镜头指派保存失败")
        fallback_ratio = _project_fallback_ratio(session, project.id)
        threshold_exceeded = (
            fallback_ratio * 100 > settings.auto_fallback_max_ratio_percent
        )
        requires_review = (
            settings.auto_fallback_review_required or threshold_exceeded
            if review_required is None
            else review_required
        )
        assignment.manual_confirmed = not requires_review
        assignment.selection_reason = (
            f"{AUTO_REASON_PREFIX}：{candidate['selection_stage']}；"
            f"项目固定种子；兜底占比 {fallback_ratio * 100:.1f}%"
        )
        session.add(assignment)
        session.commit()
        selected.append(assignment.id)
        used_shot_ids.add(candidate["media_shot_id"])
        used_media_ids.add(media_id)
        last_media_id = media_id
        coverage = timeline_composer.scene_coverage(session, scene)
        if coverage["complete"]:
            break
    return _result(selected, coverage, threshold_exceeded)


def _weighted_order(project_id: str, scene_id: str, candidates: list[dict]) -> list[dict]:
    seed = int.from_bytes(
        hashlib.sha256(f"{project_id}:{scene_id}:fallback-v1".encode()).digest()[:8],
        "big",
    )
    randomizer = random.Random(seed)
    ranked = []
    for candidate in sorted(candidates, key=lambda item: item["id"]):
        weight = max(0.05, float(candidate.get("scores", {}).get("total", 0)))
        ranked.append((randomizer.random() ** (1 / weight), candidate))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [candidate for _, candidate in ranked]


def _used_project_assets(session: Session, project_id: str) -> tuple[set[str], set[str]]:
    assignments = list(
        session.exec(
            select(SceneAssignment).where(SceneAssignment.project_id == project_id)
        ).all()
    )
    shot_ids = {item.media_shot_id for item in assignments}
    media_ids = set()
    for shot_id in shot_ids:
        shot = session.get(MediaShot, shot_id)
        if shot:
            media_ids.add(shot.media_file_id)
    return shot_ids, media_ids


def _last_scene_media_id(
    session: Session, assignments: list[SceneAssignment]
) -> str | None:
    if not assignments:
        return None
    shot = session.get(MediaShot, assignments[-1].media_shot_id)
    return shot.media_file_id if shot else None


def _trailing_auto_fallback_count(assignments: list[SceneAssignment]) -> int:
    count = 0
    for assignment in reversed(assignments):
        if not assignment.selection_reason.startswith(AUTO_REASON_PREFIX):
            break
        count += 1
    return count


def _project_fallback_ratio(session: Session, project_id: str) -> float:
    scenes = list(
        session.exec(select(VisualScene).where(VisualScene.project_id == project_id)).all()
    )
    total_ms = sum(max(0, scene.end_ms - scene.start_ms) for scene in scenes)
    fallback_ms = 0
    assignments = session.exec(
        select(SceneAssignment).where(
            SceneAssignment.project_id == project_id,
            SceneAssignment.is_fallback == True,  # noqa: E712
        )
    ).all()
    for assignment in assignments:
        if assignment.scene_offset_end_ms is not None:
            fallback_ms += max(
                0, assignment.scene_offset_end_ms - assignment.scene_offset_start_ms
            )
    return fallback_ms / total_ms if total_ms else 0


def _result(selected: list[str], coverage: dict, threshold_exceeded: bool) -> dict:
    return {
        "selected_assignment_ids": selected,
        "covered_ms": coverage["covered_ms"],
        "remaining_ms": coverage["remaining_ms"],
        "complete": coverage["complete"],
        "ratio_threshold_exceeded": threshold_exceeded,
    }
