from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
from PIL import Image
from sqlmodel import Session, select

from app.config import get_settings
from app.integrations.vision import embedding
from app.models.media import GeneratedImageVariant, MediaFile, MediaShot, SceneAssignment, SceneCandidate
from app.models.project import Project
from app.models.storyboard import VisualScene
from app.schemas.media import SceneAssignmentRequest
from app.schemas.storyboard import StoryboardContent
from app.services.media_library import retrieval_service
from app.services.rendering import timeline_composer


logger = logging.getLogger(__name__)
SELECTION_STAGE = "local_generated_image"


def score_project_images(session: Session, project: Project) -> dict:
    scenes = list(
        session.exec(
            select(VisualScene)
            .where(VisualScene.project_id == project.id)
            .order_by(VisualScene.scene_index)
        ).all()
    )
    try:
        results = [
            score_scene_images(session, project, scene.id, release_model=False)
            for scene in scenes
        ]
    finally:
        embedding.release_model()
    return {
        "project_id": project.id,
        "scene_count": len(results),
        "qualified_count": sum(item["qualified_count"] for item in results),
        "review_required_count": sum(not item["has_qualified_candidate"] for item in results),
        "scenes": results,
    }


def score_scene_images(
    session: Session,
    project: Project,
    scene_id: str,
    release_model: bool = True,
) -> dict:
    scene = session.get(VisualScene, scene_id)
    if not scene or scene.project_id != project.id:
        raise ValueError("视觉场景不存在")
    if not scene.storyboard_json:
        raise ValueError(f"场景 {scene.scene_index} 尚未生成 Storyboard")
    storyboard = StoryboardContent.model_validate_json(scene.storyboard_json)
    rows = _generated_candidate_rows(session, project.id, scene.id)
    if not rows:
        return {
            "scene_id": scene.id,
            "candidate_count": 0,
            "qualified_count": 0,
            "has_qualified_candidate": False,
            "semantic_error": None,
        }

    settings = get_settings()
    query = _semantic_query(scene, storyboard)
    avoid_query = ", ".join(storyboard.avoid)
    paths = [Path(media_file.path) for _, _, media_file, _ in rows]
    semantic_error = None
    try:
        semantic_scores = _semantic_scores(query, avoid_query, paths)
    except (OSError, RuntimeError, ValueError) as exc:
        logger.exception("Generated-image semantic scoring failed for scene %s", scene.id)
        semantic_error = str(exc)
        semantic_scores = {}
    finally:
        if release_model:
            embedding.release_model()

    qualified_count = 0
    for candidate, shot, media_file, variant in rows:
        path = Path(media_file.path)
        technical = _technical_assessment(path, variant.width, variant.height, settings)
        semantic, avoid_score = semantic_scores.get(path, (0.0, 0.0))
        avoid_penalty = max(0.0, avoid_score - semantic - 0.05)
        total = max(
            0.0,
            min(
                1.0,
                semantic * settings.image_selection_semantic_weight
                + technical["score"] * settings.image_selection_technical_weight
                - avoid_penalty * 0.25,
            ),
        )
        conflicts = list(technical["conflicts"])
        if semantic_error:
            conflicts.append("语义评分不可用，需人工确认")
        elif semantic < settings.image_selection_min_semantic_score:
            conflicts.append(
                f"语义匹配度低于阈值（{semantic:.1%} < "
                f"{settings.image_selection_min_semantic_score:.1%}）"
            )
        if avoid_penalty >= 0.05:
            conflicts.append("画面与 Storyboard 的应避免内容相似，需人工确认")
        qualified = (
            not conflicts
            and total >= settings.image_selection_min_total_score
        )
        if not qualified and not conflicts:
            conflicts.append(
                f"综合评分低于阈值（{total:.1%} < "
                f"{settings.image_selection_min_total_score:.1%}）"
            )
        candidate.semantic_score = round(semantic, 4)
        candidate.text_score = round(max(0.0, 1.0 - avoid_score), 4)
        candidate.tag_score = 0.0
        candidate.technical_score = round(technical["score"], 4)
        candidate.total_score = round(total, 4)
        candidate.status = "QUALIFIED" if qualified else "LOW_RELEVANCE"
        candidate.conflicts_json = json.dumps(conflicts, ensure_ascii=False)
        technical_payload = _json_object(shot.technical_json)
        technical_payload["generated_image_review"] = {
            **technical["metrics"],
            "semantic_score": round(semantic, 4),
            "avoid_score": round(avoid_score, 4),
            "avoid_penalty": round(avoid_penalty, 4),
            "total_score": round(total, 4),
            "status": candidate.status,
            "conflicts": conflicts,
        }
        shot.technical_json = json.dumps(technical_payload, ensure_ascii=False)
        session.add(candidate)
        session.add(shot)
        qualified_count += int(qualified)
    session.commit()
    return {
        "scene_id": scene.id,
        "candidate_count": len(rows),
        "qualified_count": qualified_count,
        "has_qualified_candidate": qualified_count > 0,
        "semantic_error": semantic_error,
    }


def auto_assign_best_image(
    session: Session,
    project: Project,
    scene_id: str,
    review_required: bool = False,
) -> dict:
    scene = session.get(VisualScene, scene_id)
    if not scene or scene.project_id != project.id:
        raise ValueError("视觉场景不存在")
    coverage = timeline_composer.scene_coverage(session, scene)
    if coverage["complete"]:
        return {"selected_assignment_ids": [], **coverage, "reason": "场景已完成选图"}
    if timeline_composer.scene_assignments(session, scene.id):
        return {"selected_assignment_ids": [], **coverage, "reason": "保留现有人工镜头轨道"}

    variants = {
        item.candidate_id: item.variant_index
        for item in session.exec(
            select(GeneratedImageVariant).where(
                GeneratedImageVariant.project_id == project.id,
                GeneratedImageVariant.scene_id == scene.id,
            )
        ).all()
        if item.candidate_id
    }
    candidates = list(
        session.exec(
            select(SceneCandidate).where(
                SceneCandidate.project_id == project.id,
                SceneCandidate.scene_id == scene.id,
                SceneCandidate.selection_stage == SELECTION_STAGE,
                SceneCandidate.status == "QUALIFIED",
            )
        ).all()
    )
    candidates.sort(key=lambda item: (-item.total_score, variants.get(item.id, 9999)))
    if not candidates:
        return {"selected_assignment_ids": [], **coverage, "reason": "没有通过质量检查的候选图"}

    best = candidates[0]
    runner_up = candidates[1] if len(candidates) > 1 else None
    margin = best.total_score - runner_up.total_score if runner_up else 1.0
    result = retrieval_service.assign_candidate(
        session,
        project,
        scene.id,
        SceneAssignmentRequest(candidate_id=best.id),
        auto_approved=not review_required,
        review_required=review_required,
    )
    assignment = session.get(SceneAssignment, result["id"])
    if assignment:
        review_label = "，等待人工复核" if review_required else "，自动审核通过"
        assignment.selection_reason = (
            f"系统综合评分自动选图{review_label}：总分 {best.total_score:.1%}，"
            f"语义 {best.semantic_score:.1%}，技术质量 {best.technical_score:.1%}，"
            f"领先候选 {margin:.1%}"
        )
        session.add(assignment)
        session.commit()
    return {
        "selected_assignment_ids": [result["id"]],
        "covered_ms": result["coverage"]["covered_ms"],
        "remaining_ms": result["coverage"]["remaining_ms"],
        "complete": result["coverage"]["complete"],
        "reason": assignment.selection_reason if assignment else "系统综合评分自动选图",
    }


def _generated_candidate_rows(
    session: Session, project_id: str, scene_id: str
) -> list[tuple[SceneCandidate, MediaShot, MediaFile, GeneratedImageVariant]]:
    variants = list(
        session.exec(
            select(GeneratedImageVariant)
            .where(
                GeneratedImageVariant.project_id == project_id,
                GeneratedImageVariant.scene_id == scene_id,
                GeneratedImageVariant.status == "completed",
            )
            .order_by(GeneratedImageVariant.variant_index)
        ).all()
    )
    rows = []
    for variant in variants:
        candidate = session.get(SceneCandidate, variant.candidate_id) if variant.candidate_id else None
        media_file = session.get(MediaFile, variant.media_file_id) if variant.media_file_id else None
        shot = (
            session.exec(select(MediaShot).where(MediaShot.media_file_id == media_file.id)).first()
            if media_file
            else None
        )
        if candidate and shot and media_file:
            rows.append((candidate, shot, media_file, variant))
    return rows


def _semantic_query(scene: VisualScene, storyboard: StoryboardContent) -> str:
    return " ".join(
        part
        for part in [
            storyboard.primary_query,
            *storyboard.alternative_queries,
            storyboard.visual_summary,
            scene.narration,
            *storyboard.entities,
            *storyboard.locations,
            storyboard.time_period,
            "must include " + ", ".join(storyboard.must_include) if storyboard.must_include else "",
        ]
        if part
    )


def _semantic_scores(
    query: str, avoid_query: str, paths: list[Path]
) -> dict[Path, tuple[float, float]]:
    query_vector = np.asarray(embedding.embed_text(query), dtype=np.float32)
    avoid_vector = (
        np.asarray(embedding.embed_text(avoid_query), dtype=np.float32)
        if avoid_query
        else None
    )
    scores = {}
    for path in paths:
        image_vector = np.asarray(embedding.embed_media("", [path]), dtype=np.float32)
        semantic = float(np.clip(np.dot(query_vector, image_vector), 0.0, 1.0))
        avoid = (
            float(np.clip(np.dot(avoid_vector, image_vector), 0.0, 1.0))
            if avoid_vector is not None
            else 0.0
        )
        scores[path] = (semantic, avoid)
    return scores


def _technical_assessment(path: Path, target_width: int, target_height: int, settings) -> dict:
    conflicts: list[str] = []
    try:
        with Image.open(path) as source:
            source.verify()
        with Image.open(path) as source:
            image = source.convert("RGB")
            width, height = image.size
            image.thumbnail((512, 512))
            pixels = np.asarray(image, dtype=np.float32) / 255.0
    except (OSError, ValueError) as exc:
        return {
            "score": 0.0,
            "metrics": {"decode_error": str(exc)},
            "conflicts": ["图片文件无法完整解码"],
        }

    luminance = pixels[..., 0] * 0.2126 + pixels[..., 1] * 0.7152 + pixels[..., 2] * 0.0722
    mean = float(luminance.mean())
    contrast = float(luminance.std())
    black_ratio = float((luminance <= 0.03).mean())
    white_ratio = float((luminance >= 0.97).mean())
    clipped_ratio = max(black_ratio, white_ratio)
    laplacian = (
        -4 * luminance[1:-1, 1:-1]
        + luminance[:-2, 1:-1]
        + luminance[2:, 1:-1]
        + luminance[1:-1, :-2]
        + luminance[1:-1, 2:]
    )
    sharpness = float(laplacian.var()) if laplacian.size else 0.0
    target_aspect = target_width / target_height
    aspect_error = abs(width / height - target_aspect) / target_aspect
    if width < target_width or height < target_height:
        conflicts.append(f"分辨率不足（{width}×{height}）")
    if aspect_error > 0.08:
        conflicts.append("画面比例偏离目标 16:9")
    if mean < 0.06:
        conflicts.append("画面整体严重欠曝")
    elif mean > 0.94:
        conflicts.append("画面整体严重过曝")
    if contrast < 0.025:
        conflicts.append("画面对比度过低或接近纯色")
    if sharpness < settings.image_selection_min_sharpness:
        conflicts.append("画面清晰度不足")
    if clipped_ratio > settings.image_selection_max_clipped_ratio:
        conflicts.append("黑场或高光溢出占比过高")

    score = (
        min(width / target_width, height / target_height, 1.0) * 0.10
        + max(0.0, 1.0 - aspect_error / 0.08) * 0.15
        + max(0.0, 1.0 - abs(mean - 0.5) / 0.5) * 0.15
        + min(contrast / 0.18, 1.0) * 0.20
        + min(sharpness / 0.015, 1.0) * 0.30
        + max(0.0, 1.0 - clipped_ratio / settings.image_selection_max_clipped_ratio) * 0.10
    )
    return {
        "score": round(max(0.0, min(score, 1.0)), 4),
        "metrics": {
            "width": width,
            "height": height,
            "mean_luminance": round(mean, 4),
            "contrast": round(contrast, 4),
            "sharpness": round(sharpness, 6),
            "black_ratio": round(black_ratio, 4),
            "white_ratio": round(white_ratio, 4),
            "aspect_error": round(aspect_error, 4),
        },
        "conflicts": conflicts,
    }


def _json_object(value: str) -> dict:
    try:
        result = json.loads(value or "{}")
        return result if isinstance(result, dict) else {}
    except json.JSONDecodeError:
        return {}
