import json
import re
from uuid import uuid4

from sqlmodel import Session, select

from app.infrastructure import gpu_resource
from app.integrations.vision.vector_index import search as vector_search
from app.models.media import (
    LIBRARY_ROLE_LANDSCAPE_FALLBACK,
    LIBRARY_ROLE_PROJECT_GENERATED,
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
from app.services.rendering import timeline_composer


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
    owner = f"scene-media-search:project:{project.id}:scene:{scene_id}"
    with gpu_resource.exclusive_gpu(owner):
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
                from app.services.media_library import fallback_service

                result["auto_fallback"] = fallback_service.auto_fill_scene(
                    session, project, scene, result["candidates"]
                )
        result["online_search"] = attempts
        return result


def _search_available_candidates(
    session: Session, project: Project, scene_id: str
) -> dict:
    scene = _require_scene(session, project.id, scene_id)
    if not scene.storyboard_json:
        raise ValueError("请先生成该场景的 Storyboard")
    storyboard = StoryboardContent.model_validate_json(scene.storyboard_json)

    assignments = session.exec(
        select(SceneAssignment).where(SceneAssignment.scene_id == scene.id)
    ).all()
    assigned_candidate_ids = {item.candidate_id for item in assignments if item.candidate_id}
    existing = session.exec(
        select(SceneCandidate).where(SceneCandidate.scene_id == scene.id)
    ).all()
    preserved_candidates = []
    for candidate in existing:
        if candidate.id in assigned_candidate_ids:
            preserved_candidates.append(candidate)
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
    preserved_shot_ids = set()
    for preserved_candidate in preserved_candidates:
        preserved_shot = session.get(MediaShot, preserved_candidate.media_shot_id)
        preserved_file = (
            session.get(MediaFile, preserved_shot.media_file_id) if preserved_shot else None
        )
        if preserved_shot and preserved_file:
            candidates.append((preserved_candidate, preserved_shot, preserved_file))
            preserved_shot_ids.add(preserved_shot.id)
    for _, shot, media_file, scored in ranked:
        if len(candidates) >= MAX_CANDIDATES:
            break
        if shot.id in preserved_shot_ids:
            continue
        candidate = SceneCandidate(
            id=f"candidate_{uuid4().hex}",
            project_id=project.id,
            scene_id=scene.id,
            media_shot_id=shot.id,
            source=media_file.provider,
            query=storyboard.primary_query,
            selection_stage=(
                "manual_upload"
                if media_file.provider == "manual_upload"
                else "local_semantic"
                if media_file.provider == "local"
                else "remote_semantic"
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


def register_manual_asset_candidates(
    session: Session, project: Project, scene_id: str, media_id: str
) -> list[dict]:
    """Expose every successfully ingested shot from a user upload for explicit selection."""
    scene = _require_scene(session, project.id, scene_id)
    media_file = session.get(MediaFile, media_id)
    if not media_file or not media_file.enabled or media_file.review_status != "approved":
        raise ValueError("上传素材不存在或当前不可用")
    shots = session.exec(
        select(MediaShot)
        .where(MediaShot.media_file_id == media_file.id, MediaShot.status == "ready")
        .order_by(MediaShot.shot_index)
    ).all()
    if not shots:
        raise ValueError("上传素材没有可用镜头，请检查文件格式或处理日志")

    candidates: list[tuple[SceneCandidate, MediaShot]] = []
    for shot in shots:
        candidate = session.exec(
            select(SceneCandidate).where(
                SceneCandidate.scene_id == scene.id,
                SceneCandidate.media_shot_id == shot.id,
                SceneCandidate.selection_stage == "manual_upload",
            )
        ).first()
        if not candidate:
            technical_score = _technical_score(media_file)
            candidate = SceneCandidate(
                id=f"candidate_{uuid4().hex}",
                project_id=project.id,
                scene_id=scene.id,
                media_shot_id=shot.id,
                source="manual_upload",
                query="人工上传替换素材",
                technical_score=technical_score,
                total_score=technical_score,
                status="QUALIFIED",
                selection_stage="manual_upload",
                conflicts_json="[]",
            )
            session.add(candidate)
        candidates.append((candidate, shot))
    session.commit()
    return [_serialize_candidate(session, candidate, shot, media_file) for candidate, shot in candidates]


def assign_candidate(
    session: Session,
    project: Project,
    scene_id: str,
    payload: SceneAssignmentRequest,
    auto_approved: bool = False,
    review_required: bool = False,
) -> dict:
    scene = _require_scene(session, project.id, scene_id)
    candidate = session.get(SceneCandidate, payload.candidate_id)
    if not candidate or candidate.project_id != project.id or candidate.scene_id != scene.id:
        raise ValueError("候选素材不存在或不属于当前场景")
    if candidate.status != "QUALIFIED" and not payload.manual_override:
        raise ValueError("该候选存在冲突或相关度不足，需要人工确认后才能指派")
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

    assignments = timeline_composer.scene_assignments(session, scene.id)
    if payload.append and any(item.candidate_id == candidate.id for item in assignments):
        raise ValueError("该候选已经在当前场景的镜头轨道中")
    if payload.append:
        _ensure_unique_scene_content(session, assignments, media_file)
    now = utc_now_iso()
    if payload.append or not assignments:
        assignment = SceneAssignment(
            id=f"assignment_{uuid4().hex}",
            project_id=project.id,
            scene_id=scene.id,
            media_shot_id=shot.id,
            sequence_index=len(assignments) + 1,
            created_at=now,
        )
        assignments.append(assignment)
    else:
        assignment = assignments[0]
        for extra in assignments[1:]:
            session.delete(extra)
        assignments = [assignment]
    assignment.media_shot_id = shot.id
    assignment.candidate_id = candidate.id
    assignment.trim_start_ms = payload.trim_start_ms
    assignment.trim_end_ms = payload.trim_end_ms
    assignment.playback_speed = payload.playback_speed
    assignment.display_duration_ms = (
        payload.display_duration_ms
        or (scene.end_ms - scene.start_ms if candidate.selection_stage == "local_generated_image" else None)
    )
    assignment.render_mode = payload.render_mode
    assignment.motion_type = payload.motion_type
    assignment.zoom_start = payload.zoom_start
    assignment.zoom_end = payload.zoom_end
    assignment.pan_direction = payload.pan_direction
    assignment.crop_anchor = payload.crop_anchor
    assignment.transition = payload.transition
    assignment.manual_confirmed = not review_required
    assignment.selection_stage = candidate.selection_stage
    conflicts = json.loads(candidate.conflicts_json)
    assignment.selection_reason = (
        f"系统已按匹配度预选，等待人工复核（{candidate.total_score:.1%}）"
        if review_required
        else
        f"系统按匹配度自动审核通过（{candidate.total_score:.1%}）"
        if auto_approved
        else "人工确认接受候选冲突：" + "；".join(conflicts)
        if conflicts
        else "人工确认接受低相关候选"
        if candidate.status != "QUALIFIED"
        else _selection_reason(candidate.selection_stage)
    )
    assignment.is_fallback = candidate.is_fallback
    assignment.updated_at = now
    _, covered_ms = timeline_composer.reflow_scene_assignments(session, scene, assignments)
    scene_duration_ms = scene.end_ms - scene.start_ms
    scene.status = "assigned" if covered_ms >= scene_duration_ms else "partially_assigned"
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
        "display_duration_ms": assignment.display_duration_ms,
        "motion_type": assignment.motion_type,
        "zoom_start": assignment.zoom_start,
        "zoom_end": assignment.zoom_end,
        "pan_direction": assignment.pan_direction,
        "crop_anchor": assignment.crop_anchor,
        "transition": assignment.transition,
        "manual_confirmed": assignment.manual_confirmed,
        "selection_stage": assignment.selection_stage,
        "selection_reason": assignment.selection_reason,
        "is_fallback": assignment.is_fallback,
        "sequence_index": assignment.sequence_index,
        "scene_offset_start_ms": assignment.scene_offset_start_ms,
        "scene_offset_end_ms": assignment.scene_offset_end_ms,
        "coverage": _coverage_payload(covered_ms, scene_duration_ms),
    }


def auto_assign_qualified_candidates(
    session: Session,
    project: Project,
    scene_id: str,
    review_required: bool = False,
) -> dict:
    """Fill one scene with qualified candidates in descending match-score order."""
    scene = _require_scene(session, project.id, scene_id)
    selected_assignment_ids: list[str] = []
    existing_assignments = timeline_composer.scene_assignments(session, scene.id)
    for assignment in existing_assignments:
        candidate = session.get(SceneCandidate, assignment.candidate_id) if assignment.candidate_id else None
        if candidate and candidate.status == "QUALIFIED" and not assignment.manual_confirmed:
            assignment.manual_confirmed = not review_required
            assignment.selection_reason = (
                f"系统已按匹配度预选，等待人工复核（{candidate.total_score:.1%}）"
                if review_required
                else f"系统按匹配度自动审核通过（{candidate.total_score:.1%}）"
            )
            session.add(assignment)
            selected_assignment_ids.append(assignment.id)
    session.commit()
    candidates = session.exec(
        select(SceneCandidate)
        .where(
            SceneCandidate.project_id == project.id,
            SceneCandidate.scene_id == scene.id,
            SceneCandidate.status == "QUALIFIED",
        )
        .order_by(SceneCandidate.total_score.desc(), SceneCandidate.id)
    ).all()
    for candidate in candidates:
        coverage = timeline_composer.scene_coverage(session, scene)
        if coverage["complete"]:
            break
        try:
            assignment = assign_candidate(
                session,
                project,
                scene.id,
                SceneAssignmentRequest(candidate_id=candidate.id, append=True),
                auto_approved=not review_required,
                review_required=review_required,
            )
        except ValueError as exc:
            if "相同的素材内容" in str(exc) or "已经在当前场景" in str(exc):
                continue
            raise
        selected_assignment_ids.append(assignment["id"])
    coverage = timeline_composer.scene_coverage(session, scene)
    return {
        "selected_assignment_ids": selected_assignment_ids,
        "covered_ms": coverage["covered_ms"],
        "remaining_ms": coverage["remaining_ms"],
        "complete": coverage["complete"],
    }


def _ensure_unique_scene_content(
    session: Session,
    assignments: list[SceneAssignment],
    incoming_media: MediaFile,
) -> None:
    """Reject the same source or byte-identical content within one visual scene."""
    for assignment in assignments:
        shot = session.get(MediaShot, assignment.media_shot_id)
        media_file = session.get(MediaFile, shot.media_file_id) if shot else None
        if not media_file:
            continue
        if (
            media_file.id == incoming_media.id
            or (
                media_file.provider == incoming_media.provider
                and media_file.provider_asset_id
                and media_file.provider_asset_id == incoming_media.provider_asset_id
            )
            or (
                media_file.file_hash
                and incoming_media.file_hash
                and media_file.file_hash == incoming_media.file_hash
            )
        ):
            raise ValueError("同一个分镜头中禁止使用相同的素材内容")


def list_scene_assignments(session: Session, project_id: str, scene_id: str) -> dict:
    scene = _require_scene(session, project_id, scene_id)
    assignments, covered_ms = timeline_composer.reflow_scene_assignments(session, scene)
    session.commit()
    coverage = _coverage_payload(covered_ms, scene.end_ms - scene.start_ms)
    coverage["review_required"] = any(not item.manual_confirmed for item in assignments)
    return {
        "assignments": [_serialize_assignment(session, item) for item in assignments],
        "coverage": coverage,
    }


def list_project_assignment_coverage(session: Session, project_id: str) -> dict:
    scenes = list(
        session.exec(
            select(VisualScene)
            .where(VisualScene.project_id == project_id)
            .order_by(VisualScene.scene_index)
        ).all()
    )
    coverage = {}
    for scene in scenes:
        _, covered_ms = timeline_composer.reflow_scene_assignments(session, scene)
        duration_ms = scene.end_ms - scene.start_ms
        scene.status = "assigned" if covered_ms >= duration_ms else "partially_assigned" if covered_ms else "generated"
        session.add(scene)
        item_coverage = _coverage_payload(covered_ms, duration_ms)
        scene_assignments = timeline_composer.scene_assignments(session, scene.id)
        item_coverage["review_required"] = any(
            not item.manual_confirmed for item in scene_assignments
        )
        coverage[scene.id] = item_coverage
    session.commit()
    return {"scenes": coverage}


def delete_scene_assignment(
    session: Session, project_id: str, scene_id: str, assignment_id: str
) -> dict:
    scene = _require_scene(session, project_id, scene_id)
    assignment = session.get(SceneAssignment, assignment_id)
    if not assignment or assignment.scene_id != scene.id or assignment.project_id != project_id:
        raise ValueError("镜头轨道指派不存在")
    session.delete(assignment)
    session.flush()
    assignments, covered_ms = timeline_composer.reflow_scene_assignments(session, scene)
    duration_ms = scene.end_ms - scene.start_ms
    scene.status = "assigned" if covered_ms >= duration_ms else "partially_assigned" if assignments else "generated"
    session.add(scene)
    session.commit()
    return list_scene_assignments(session, project_id, scene_id)


def reorder_scene_assignments(
    session: Session, project_id: str, scene_id: str, assignment_ids: list[str]
) -> dict:
    scene = _require_scene(session, project_id, scene_id)
    assignments = timeline_composer.scene_assignments(session, scene.id)
    by_id = {item.id: item for item in assignments}
    if set(assignment_ids) != set(by_id):
        raise ValueError("排序列表必须完整包含当前场景的全部镜头")
    for index, assignment_id in enumerate(assignment_ids, start=1):
        by_id[assignment_id].sequence_index = -index
        session.add(by_id[assignment_id])
    session.flush()
    ordered = [by_id[assignment_id] for assignment_id in assignment_ids]
    _, covered_ms = timeline_composer.reflow_scene_assignments(session, scene, ordered)
    duration_ms = scene.end_ms - scene.start_ms
    scene.status = "assigned" if covered_ms >= duration_ms else "partially_assigned"
    session.add(scene)
    session.commit()
    return list_scene_assignments(session, project_id, scene_id)


def update_scene_assignment_render(
    session: Session,
    project_id: str,
    scene_id: str,
    assignment_id: str,
    values: dict,
) -> dict:
    _require_scene(session, project_id, scene_id)
    assignment = session.get(SceneAssignment, assignment_id)
    if not assignment or assignment.project_id != project_id or assignment.scene_id != scene_id:
        raise ValueError("镜头轨道指派不存在")
    for field in (
        "render_mode",
        "motion_type",
        "zoom_start",
        "zoom_end",
        "pan_direction",
        "crop_anchor",
    ):
        setattr(assignment, field, values[field])
    assignment.updated_at = utc_now_iso()
    session.add(assignment)
    session.commit()
    return list_scene_assignments(session, project_id, scene_id)


def confirm_scene_assignments(
    session: Session, project_id: str, scene_id: str
) -> dict:
    scene = _require_scene(session, project_id, scene_id)
    assignments = timeline_composer.scene_assignments(session, scene.id)
    coverage = timeline_composer.scene_coverage(session, scene)
    if not coverage["complete"]:
        raise ValueError("当前分镜的素材轨道尚未覆盖完整，不能确认审核")
    confirmed = 0
    for assignment in assignments:
        if not assignment.manual_confirmed:
            assignment.manual_confirmed = True
            assignment.selection_reason = (
                f"{assignment.selection_reason}；人工复核通过".strip("；")
            )
            assignment.updated_at = utc_now_iso()
            session.add(assignment)
            confirmed += 1
    if not confirmed:
        raise ValueError("当前分镜没有等待确认的素材")
    session.commit()
    return list_scene_assignments(session, project_id, scene_id)


def confirm_scene_fallback_assignments(
    session: Session, project_id: str, scene_id: str
) -> dict:
    """Compatibility alias for clients using the old fallback-only action."""
    return confirm_scene_assignments(session, project_id, scene_id)


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
        "manual_upload": LIBRARY_ROLE_SEMANTIC,
        "local_generated_image": LIBRARY_ROLE_PROJECT_GENERATED,
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
        "local_generated_image": "本地模型生成的分镜图片",
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


def _serialize_assignment(session: Session, assignment: SceneAssignment) -> dict:
    shot = session.get(MediaShot, assignment.media_shot_id)
    media_file = session.get(MediaFile, shot.media_file_id) if shot else None
    if not shot or not media_file:
        raise ValueError("镜头轨道包含不存在的素材")
    return {
        "id": assignment.id,
        "candidate_id": assignment.candidate_id,
        "media_shot_id": assignment.media_shot_id,
        "sequence_index": assignment.sequence_index,
        "scene_offset_start_ms": assignment.scene_offset_start_ms,
        "scene_offset_end_ms": assignment.scene_offset_end_ms,
        "trim_start_ms": assignment.trim_start_ms,
        "trim_end_ms": assignment.trim_end_ms,
        "playback_speed": assignment.playback_speed,
        "display_duration_ms": assignment.display_duration_ms,
        "render_mode": assignment.render_mode,
        "motion_type": assignment.motion_type,
        "zoom_start": assignment.zoom_start,
        "zoom_end": assignment.zoom_end,
        "pan_direction": assignment.pan_direction,
        "crop_anchor": assignment.crop_anchor,
        "transition": assignment.transition,
        "manual_confirmed": assignment.manual_confirmed,
        "selection_stage": assignment.selection_stage,
        "selection_reason": assignment.selection_reason,
        "is_fallback": assignment.is_fallback,
        "shot": serialize_shot(session, shot),
        "media": {
            "id": media_file.id,
            "filename": media_file.filename,
            "media_type": media_file.media_type,
            "duration_ms": media_file.duration_ms,
            "width": media_file.width,
            "height": media_file.height,
            "provider": media_file.provider,
        },
    }


def _coverage_payload(covered_ms: int, duration_ms: int) -> dict:
    return {
        "covered_ms": covered_ms,
        "duration_ms": duration_ms,
        "remaining_ms": max(0, duration_ms - covered_ms),
        "complete": covered_ms >= duration_ms,
    }
