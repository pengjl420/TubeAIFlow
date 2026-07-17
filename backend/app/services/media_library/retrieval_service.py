import json
import re
from uuid import uuid4

from sqlmodel import Session, select

from app.models.media import MediaFile, MediaShot, SceneAssignment, SceneCandidate
from app.models.project import Project
from app.models.storyboard import VisualScene
from app.schemas.media import SceneAssignmentRequest
from app.schemas.storyboard import StoryboardContent
from app.shared.time import utc_now_iso


MIN_LOCAL_RELEVANCE = 0.25
MAX_CANDIDATES = 20


def search_scene_candidates(
    session: Session, project: Project, scene_id: str
) -> dict:
    scene = _require_scene(session, project.id, scene_id)
    if not scene.storyboard_json:
        raise ValueError("请先生成该场景的 Storyboard")
    storyboard = StoryboardContent.model_validate_json(scene.storyboard_json)

    assignment = session.exec(
        select(SceneAssignment).where(SceneAssignment.scene_id == scene.id)
    ).first()
    existing = session.exec(
        select(SceneCandidate).where(SceneCandidate.scene_id == scene.id)
    ).all()
    preserved_candidate = None
    for candidate in existing:
        if assignment and candidate.id == assignment.candidate_id:
            preserved_candidate = candidate
        else:
            session.delete(candidate)

    rows = session.exec(
        select(MediaShot, MediaFile)
        .join(MediaFile, MediaFile.id == MediaShot.media_file_id)
        .where(MediaShot.status == "ready", MediaFile.status == "ready")
    ).all()
    ranked = []
    for shot, media_file in rows:
        scored = _score_candidate(storyboard, shot, media_file)
        ranked.append((scored["total_score"], shot, media_file, scored))
    ranked.sort(key=lambda item: item[0], reverse=True)

    candidates = []
    if preserved_candidate:
        preserved_shot = session.get(MediaShot, preserved_candidate.media_shot_id)
        preserved_file = (
            session.get(MediaFile, preserved_shot.media_file_id) if preserved_shot else None
        )
        if preserved_shot and preserved_file:
            candidates.append((preserved_candidate, preserved_shot, preserved_file))
    for _, shot, media_file, scored in ranked:
        if len(candidates) >= MAX_CANDIDATES:
            break
        if preserved_candidate and shot.id == preserved_candidate.media_shot_id:
            continue
        candidate = SceneCandidate(
            id=f"candidate_{uuid4().hex}",
            project_id=project.id,
            scene_id=scene.id,
            media_shot_id=shot.id,
            source=media_file.provider,
            query=storyboard.primary_query,
            **scored,
        )
        session.add(candidate)
        candidates.append((candidate, shot, media_file))
    session.commit()

    serialized = [_serialize_candidate(*item) for item in candidates]
    overall_status = "NO_RESULT"
    if serialized:
        overall_status = (
            "QUALIFIED"
            if any(item["status"] == "QUALIFIED" for item in serialized)
            else "LOW_RELEVANCE"
        )
    return {"scene_id": scene.id, "status": overall_status, "candidates": serialized}


def list_scene_candidates(
    session: Session, project_id: str, scene_id: str
) -> list[dict]:
    _require_scene(session, project_id, scene_id)
    candidates = session.exec(
        select(SceneCandidate)
        .where(SceneCandidate.project_id == project_id, SceneCandidate.scene_id == scene_id)
        .order_by(SceneCandidate.total_score.desc())
    ).all()
    result = []
    for candidate in candidates:
        shot = session.get(MediaShot, candidate.media_shot_id)
        media_file = session.get(MediaFile, shot.media_file_id) if shot else None
        if shot and media_file:
            result.append(_serialize_candidate(candidate, shot, media_file))
    return result


def assign_candidate(
    session: Session,
    project: Project,
    scene_id: str,
    payload: SceneAssignmentRequest,
) -> dict:
    scene = _require_scene(session, project.id, scene_id)
    candidate = session.get(SceneCandidate, payload.candidate_id)
    if not candidate or candidate.project_id != project.id or candidate.scene_id != scene.id:
        raise ValueError("候选素材不存在或不属于当前场景")
    if candidate.status != "QUALIFIED":
        raise ValueError("只有 QUALIFIED 候选可以直接指派")
    shot = session.get(MediaShot, candidate.media_shot_id)
    if not shot:
        raise ValueError("候选素材镜头不存在")
    if payload.trim_end_ms is not None and payload.trim_end_ms <= payload.trim_start_ms:
        raise ValueError("素材裁剪结束时间必须晚于开始时间")
    if shot.end_ms is not None and payload.trim_start_ms >= shot.end_ms - shot.start_ms:
        raise ValueError("素材裁剪开始时间超出镜头范围")
    if (
        shot.end_ms is not None
        and payload.trim_end_ms is not None
        and payload.trim_end_ms > shot.end_ms - shot.start_ms
    ):
        raise ValueError("素材裁剪结束时间超出镜头范围")

    assignment = session.exec(
        select(SceneAssignment).where(SceneAssignment.scene_id == scene.id)
    ).first()
    now = utc_now_iso()
    if not assignment:
        assignment = SceneAssignment(
            id=f"assignment_{uuid4().hex}",
            project_id=project.id,
            scene_id=scene.id,
            media_shot_id=shot.id,
            created_at=now,
        )
    assignment.media_shot_id = shot.id
    assignment.candidate_id = candidate.id
    assignment.trim_start_ms = payload.trim_start_ms
    assignment.trim_end_ms = payload.trim_end_ms
    assignment.playback_speed = payload.playback_speed
    assignment.transition = payload.transition
    assignment.manual_confirmed = True
    assignment.updated_at = now
    scene.status = "assigned"
    scene.updated_at = now
    session.add(assignment)
    session.add(scene)
    session.commit()
    session.refresh(assignment)
    return {
        "id": assignment.id,
        "project_id": assignment.project_id,
        "scene_id": assignment.scene_id,
        "candidate_id": assignment.candidate_id,
        "media_shot_id": assignment.media_shot_id,
        "trim_start_ms": assignment.trim_start_ms,
        "trim_end_ms": assignment.trim_end_ms,
        "playback_speed": assignment.playback_speed,
        "transition": assignment.transition,
        "manual_confirmed": assignment.manual_confirmed,
    }


def _score_candidate(
    storyboard: StoryboardContent, shot: MediaShot, media_file: MediaFile
) -> dict:
    tags = json.loads(shot.tags_json)
    searchable = " ".join([shot.description, media_file.filename, *tags]).lower()
    query_tokens = _tokens(
        " ".join(
            [
                storyboard.primary_query,
                *storyboard.alternative_queries,
                storyboard.visual_summary,
                *storyboard.entities,
                *storyboard.locations,
            ]
        )
    )
    searchable_tokens = _tokens(searchable)
    overlap = query_tokens & searchable_tokens
    text_score = len(overlap) / len(query_tokens) if query_tokens else 0
    tag_tokens = _tokens(" ".join(tags))
    tag_score = len(query_tokens & tag_tokens) / len(query_tokens) if query_tokens else 0
    technical_score = _technical_score(media_file)

    conflicts = []
    for avoided in storyboard.avoid:
        if _matches_constraint(avoided, searchable, searchable_tokens):
            conflicts.append(f"avoid conflict: {avoided}")
    for required in storyboard.must_include:
        if not _matches_constraint(required, searchable, searchable_tokens):
            conflicts.append(f"missing required: {required}")

    total_score = text_score * 0.75 + tag_score * 0.15 + technical_score * 0.10
    if conflicts:
        total_score = max(0, total_score - min(0.6, len(conflicts) * 0.2))
    status = "QUALIFIED" if total_score >= MIN_LOCAL_RELEVANCE and not conflicts else "LOW_RELEVANCE"
    return {
        "semantic_score": 0.0,
        "text_score": round(text_score, 4),
        "tag_score": round(tag_score, 4),
        "technical_score": round(technical_score, 4),
        "total_score": round(total_score, 4),
        "status": status,
        "conflicts_json": json.dumps(conflicts, ensure_ascii=False),
    }


def _matches_constraint(value: str, searchable: str, searchable_tokens: set[str]) -> bool:
    normalized = value.strip().lower()
    if not normalized:
        return True
    if normalized in searchable:
        return True
    tokens = _tokens(normalized)
    return bool(tokens) and tokens.issubset(searchable_tokens)


def _technical_score(media_file: MediaFile) -> float:
    if not media_file.width or not media_file.height:
        return 0.4
    landscape = media_file.width / media_file.height >= 1.5
    resolution = 1.0 if media_file.width >= 1920 and media_file.height >= 1080 else 0.7
    return resolution if landscape else resolution * 0.4


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", value.lower()))


def _require_scene(session: Session, project_id: str, scene_id: str) -> VisualScene:
    scene = session.get(VisualScene, scene_id)
    if not scene or scene.project_id != project_id:
        raise ValueError("视觉场景不存在")
    return scene


def _serialize_candidate(
    candidate: SceneCandidate, shot: MediaShot, media_file: MediaFile
) -> dict:
    return {
        "id": candidate.id,
        "scene_id": candidate.scene_id,
        "media_shot_id": shot.id,
        "source": candidate.source,
        "query": candidate.query,
        "scores": {
            "semantic": candidate.semantic_score,
            "text": candidate.text_score,
            "tags": candidate.tag_score,
            "technical": candidate.technical_score,
            "total": candidate.total_score,
        },
        "status": candidate.status,
        "conflicts": json.loads(candidate.conflicts_json),
        "shot": {
            "shot_index": shot.shot_index,
            "start_ms": shot.start_ms,
            "end_ms": shot.end_ms,
            "description": shot.description,
            "thumbnail_path": shot.thumbnail_path,
        },
        "media": {
            "id": media_file.id,
            "filename": media_file.filename,
            "path": media_file.path,
            "media_type": media_file.media_type,
            "duration_ms": media_file.duration_ms,
            "width": media_file.width,
            "height": media_file.height,
            "provider": media_file.provider,
        },
    }
