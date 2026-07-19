from sqlmodel import Session, select

from app.models.media import MediaFile, MediaShot, SceneAssignment
from app.models.storyboard import VisualScene


MIN_PLAYBACK_SPEED = 0.85
DEFAULT_IMAGE_DURATION_MS = 8_000


def scene_assignments(session: Session, scene_id: str) -> list[SceneAssignment]:
    return list(
        session.exec(
            select(SceneAssignment)
            .where(SceneAssignment.scene_id == scene_id)
            .order_by(SceneAssignment.sequence_index, SceneAssignment.created_at)
        ).all()
    )


def reflow_scene_assignments(
    session: Session,
    scene: VisualScene,
    assignments: list[SceneAssignment] | None = None,
) -> tuple[list[SceneAssignment], int]:
    """Lay placements end-to-end and return the covered duration in milliseconds."""
    assignments = assignments if assignments is not None else scene_assignments(session, scene.id)
    scene_duration_ms = scene.end_ms - scene.start_ms
    cursor_ms = 0
    for index, assignment in enumerate(assignments, start=1):
        if cursor_ms >= scene_duration_ms:
            raise ValueError("镜头轨道已经覆盖完整场景，请先删除或调整已有镜头")
        shot = session.get(MediaShot, assignment.media_shot_id)
        media_file = session.get(MediaFile, shot.media_file_id) if shot else None
        if not shot or not media_file:
            raise ValueError("镜头轨道包含不存在的素材")

        remaining_ms = scene_duration_ms - cursor_ms
        if media_file.media_type == "image":
            placement_ms = min(DEFAULT_IMAGE_DURATION_MS, remaining_ms)
        else:
            source_ms = _source_duration_ms(assignment, shot, media_file)
            if source_ms <= 0:
                raise ValueError("素材可用时长必须大于零")
            if source_ms < remaining_ms <= round(source_ms / MIN_PLAYBACK_SPEED):
                assignment.playback_speed = max(MIN_PLAYBACK_SPEED, source_ms / remaining_ms)
            output_ms = max(1, round(source_ms / assignment.playback_speed))
            placement_ms = min(output_ms, remaining_ms)

        assignment.sequence_index = index
        assignment.scene_offset_start_ms = cursor_ms
        assignment.scene_offset_end_ms = cursor_ms + placement_ms
        session.add(assignment)
        cursor_ms += placement_ms
    return assignments, cursor_ms


def scene_coverage(session: Session, scene: VisualScene) -> dict:
    assignments, covered_ms = reflow_scene_assignments(session, scene)
    duration_ms = scene.end_ms - scene.start_ms
    return {
        "assignments": assignments,
        "covered_ms": covered_ms,
        "duration_ms": duration_ms,
        "remaining_ms": max(0, duration_ms - covered_ms),
        "complete": bool(assignments) and covered_ms >= duration_ms,
        "review_required": any(not item.manual_confirmed for item in assignments),
    }


def _source_duration_ms(
    assignment: SceneAssignment, shot: MediaShot, media_file: MediaFile
) -> int:
    relative_end = assignment.trim_end_ms
    if relative_end is None:
        shot_end = shot.end_ms if shot.end_ms is not None else media_file.duration_ms
        relative_end = (shot_end - shot.start_ms) if shot_end is not None else None
    if relative_end is None:
        return 0
    return max(0, relative_end - assignment.trim_start_ms)
