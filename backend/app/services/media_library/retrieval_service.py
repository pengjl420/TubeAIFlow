import json
import re
from uuid import uuid4

from sqlmodel import Session, select

from app.integrations.vision.vector_index import search as vector_search
from app.models.media import (
    LIBRARY_ROLE_LANDSCAPE_FALLBACK,
    LIBRARY_ROLE_SEMANTIC,
    LIBRARY_ROLE_THEMED_FALLBACK,
    MediaFile,
    MediaShot,
    SceneAssignment,
    SceneCandidate,
)
from app.models.project import Project
from app.models.storyboard import VisualScene
from app.schemas.media import SceneAssignmentRequest
from app.schemas.storyboard import StoryboardContent
from app.shared.time import utc_now_iso
from app.services.media_library.ingestion_service import serialize_shot
from app.services.media_library import media_provider_service, remote_retrieval_service


MIN_LOCAL_RELEVANCE = 0.25
MAX_CANDIDATES = 20


def clear_project_scene_data(session: Session, project_id: str) -> None:
    """Invalidate candidates and assignments before replacing a project's scenes."""
    candidates = session.exec(
        select(SceneCandidate).where(SceneCandidate.project_id == project_id)
    ).all()
    assignments = session.exec(
        select(SceneAssignment).where(SceneAssignment.project_id == project_id)
    ).all()
    for item in [*candidates, *assignments]:
        session.delete(item)
    session.flush()


def search_scene_candidates(
    session: Session, project: Project, scene_id: str
) -> dict:
    result = _search_available_candidates(session, project, scene_id)
    if result["status"] == "QUALIFIED":
        result["online_search"] = []
        return result

    scene = _require_scene(session, project.id, scene_id)
    storyboard = StoryboardContent.model_validate_json(scene.storyboard_json)
    attempts = []
    for provider in media_provider_service.PROVIDER_ORDER:
        attempt = remote_retrieval_service.fetch_provider_candidates(
            session, provider, storyboard
        )
        attempts.append(attempt)
        if attempt["downloaded"]:
            result = _search_available_candidates(session, project, scene_id)
        if result["status"] == "QUALIFIED":
            break
    if result["status"] != "QUALIFIED":
        added = _append_fallback_candidates(
            session, project, scene, storyboard, LIBRARY_ROLE_THEMED_FALLBACK
        )
        if not added and storyboard.allow_landscape_fallback:
            added = _append_fallback_candidates(
                session, project, scene, storyboard, LIBRARY_ROLE_LANDSCAPE_FALLBACK
            )
        if added:
            result = {
                "scene_id": scene.id,
                "status": "FALLBACK_REQUIRED",
                "candidates": list_scene_candidates(session, project.id, scene.id),
            }
    result["online_search"] = attempts
    return result


def _search_available_candidates(
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
        .where(
            MediaShot.status == "ready",
            MediaShot.library_role == LIBRARY_ROLE_SEMANTIC,
            MediaFile.status == "ready",
            MediaFile.library_role == LIBRARY_ROLE_SEMANTIC,
            MediaFile.review_status == "approved",
            MediaFile.enabled == True,  # noqa: E712
        )
    ).all()
    vector_query = " ".join(
        [
            storyboard.primary_query,
            *storyboard.alternative_queries,
            storyboard.visual_summary,
            *storyboard.entities,
            *storyboard.locations,
        ]
    )
    vector_scores = vector_search(vector_query)
    ranked = []
    for shot, media_file in rows:
        scored = _score_candidate(
            storyboard,
            shot,
            media_file,
            vector_scores.get(shot.id, 0.0),
        )
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
            selection_stage=(
                "local_semantic" if media_file.provider == "local" else "remote_semantic"
            ),
            **scored,
        )
        session.add(candidate)
        candidates.append((candidate, shot, media_file))
    session.commit()

    serialized = [_serialize_candidate(session, *item) for item in candidates]
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
            result.append(_serialize_candidate(session, candidate, shot, media_file))
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
    media_file = session.get(MediaFile, shot.media_file_id)
    if not media_file:
        raise ValueError("候选素材文件不存在")
    _validate_candidate_role(scene, candidate, shot, media_file)
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
    assignment.selection_stage = candidate.selection_stage
    assignment.selection_reason = _selection_reason(candidate.selection_stage)
    assignment.is_fallback = candidate.is_fallback
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
        "selection_stage": assignment.selection_stage,
        "selection_reason": assignment.selection_reason,
        "is_fallback": assignment.is_fallback,
    }


def _append_fallback_candidates(
    session: Session,
    project: Project,
    scene: VisualScene,
    storyboard: StoryboardContent,
    library_role: str,
) -> int:
    existing_shot_ids = {
        item.media_shot_id
        for item in session.exec(
            select(SceneCandidate).where(SceneCandidate.scene_id == scene.id)
        ).all()
    }
    rows = session.exec(
        select(MediaShot, MediaFile)
        .join(MediaFile, MediaFile.id == MediaShot.media_file_id)
        .where(
            MediaShot.status == "ready",
            MediaShot.library_role == library_role,
            MediaFile.status == "ready",
            MediaFile.library_role == library_role,
            MediaFile.review_status == "approved",
            MediaFile.enabled == True,  # noqa: E712
        )
    ).all()
    ranked = []
    for shot, media_file in rows:
        if shot.id in existing_shot_ids:
            continue
        if (
            library_role == LIBRARY_ROLE_THEMED_FALLBACK
            and shot.fallback_category
            and shot.fallback_category.casefold() != storyboard.fallback_category.casefold()
        ):
            continue
        category_score = _fallback_match_score(
            storyboard.fallback_category,
            shot.fallback_category,
            shot.description,
            shot.tags_json,
        )
        mood_score = _fallback_match_score(
            storyboard.fallback_mood,
            shot.mood,
            shot.description,
            shot.tags_json,
        )
        technical_score = _technical_score(media_file)
        total_score = technical_score * 0.5 + category_score * 0.35 + mood_score * 0.15
        ranked.append((total_score, shot, media_file, category_score, mood_score, technical_score))
    ranked.sort(key=lambda item: item[0], reverse=True)

    added = 0
    for total_score, shot, media_file, category_score, mood_score, technical_score in ranked[:5]:
        session.add(
            SceneCandidate(
                id=f"candidate_{uuid4().hex}",
                project_id=project.id,
                scene_id=scene.id,
                media_shot_id=shot.id,
                source=media_file.provider,
                query=storyboard.fallback_category,
                semantic_score=0,
                text_score=round(category_score, 4),
                tag_score=round(mood_score, 4),
                technical_score=round(technical_score, 4),
                total_score=round(total_score, 4),
                status="QUALIFIED",
                selection_stage=library_role,
                is_fallback=True,
                conflicts_json="[]",
            )
        )
        added += 1
    if added:
        session.commit()
    return added


def _fallback_match_score(expected: str, *values: str) -> float:
    expected_tokens = _tokens(expected)
    if not expected_tokens:
        return 0.5
    combined = " ".join(values)
    if expected.casefold() in combined.casefold():
        return 1.0
    actual_tokens = _tokens(combined)
    return len(expected_tokens & actual_tokens) / len(expected_tokens)


def _validate_candidate_role(
    scene: VisualScene,
    candidate: SceneCandidate,
    shot: MediaShot,
    media_file: MediaFile,
) -> None:
    if media_file.status != "ready" or media_file.review_status != "approved" or not media_file.enabled:
        raise ValueError("候选素材当前未审核通过或已停用")
    expected_role = {
        "local_semantic": LIBRARY_ROLE_SEMANTIC,
        "remote_semantic": LIBRARY_ROLE_SEMANTIC,
        LIBRARY_ROLE_THEMED_FALLBACK: LIBRARY_ROLE_THEMED_FALLBACK,
        LIBRARY_ROLE_LANDSCAPE_FALLBACK: LIBRARY_ROLE_LANDSCAPE_FALLBACK,
    }.get(candidate.selection_stage)
    if expected_role and (shot.library_role != expected_role or media_file.library_role != expected_role):
        raise ValueError("候选素材角色与当前选择阶段不匹配")
    if candidate.selection_stage == LIBRARY_ROLE_LANDSCAPE_FALLBACK:
        storyboard = StoryboardContent.model_validate_json(scene.storyboard_json)
        if not storyboard.allow_landscape_fallback:
            raise ValueError("当前场景不允许使用纯风景最终兜底")


def _selection_reason(stage: str) -> str:
    return {
        "local_semantic": "本地语义素材命中",
        "remote_semantic": "在线语义素材命中",
        LIBRARY_ROLE_THEMED_FALLBACK: "语义素材无合格结果，使用主题化兜底",
        LIBRARY_ROLE_LANDSCAPE_FALLBACK: "语义和主题兜底均无结果，使用纯风景最终兜底",
    }.get(stage, "人工确认素材")


def _score_candidate(
    storyboard: StoryboardContent,
    shot: MediaShot,
    media_file: MediaFile,
    semantic_score: float = 0.0,
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

    total_score = (
        semantic_score * 0.55
        + text_score * 0.20
        + tag_score * 0.15
        + technical_score * 0.10
    )
    if conflicts:
        total_score = max(0, total_score - min(0.6, len(conflicts) * 0.2))
    status = "QUALIFIED" if total_score >= MIN_LOCAL_RELEVANCE and not conflicts else "LOW_RELEVANCE"
    return {
        "semantic_score": round(semantic_score, 4),
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
    session: Session,
    candidate: SceneCandidate,
    shot: MediaShot,
    media_file: MediaFile,
) -> dict:
    serialized_shot = serialize_shot(session, shot)
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
        "selection_stage": candidate.selection_stage,
        "is_fallback": candidate.is_fallback,
        "conflicts": json.loads(candidate.conflicts_json),
        "retrieval": {
            "vector_model": serialized_shot.get("vector_model") if shot.vector_id is not None else None,
            "vector_id": shot.vector_id,
        },
        "shot": serialized_shot,
        "media": {
            "id": media_file.id,
            "filename": media_file.filename,
            "path": media_file.path,
            "media_type": media_file.media_type,
            "duration_ms": media_file.duration_ms,
            "width": media_file.width,
            "height": media_file.height,
            "provider": media_file.provider,
            "library_role": media_file.library_role,
            "fallback_category": media_file.fallback_category,
            "mood": media_file.mood,
        },
    }
