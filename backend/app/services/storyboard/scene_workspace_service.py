from __future__ import annotations

import json
import uuid
from pathlib import Path

from sqlalchemy import delete
from sqlmodel import Session, select

from app.config import get_settings
from app.infrastructure.atomic_files import write_json_atomic
from app.infrastructure.project_layout import get_final_video_path, get_project_work_dir
from app.models.media import GeneratedImageVariant, MediaFile, MediaShot, SceneAssignment
from app.models.project import Project
from app.models.storyboard import VisualScene
from app.services.rendering import timeline_composer


def scene_assets(session: Session, project: Project, scene_id: str) -> dict:
    scene = _scene(session, project, scene_id)
    assignments = timeline_composer.scene_assignments(session, scene.id)
    assigned_media_ids = set()
    assignment_values = []
    for assignment in assignments:
        shot = session.get(MediaShot, assignment.media_shot_id)
        media = session.get(MediaFile, shot.media_file_id) if shot else None
        if not shot or not media:
            continue
        assigned_media_ids.add(media.id)
        assignment_values.append(_assignment_value(assignment, shot, media))
    variants = session.exec(
        select(GeneratedImageVariant)
        .where(
            GeneratedImageVariant.project_id == project.id,
            GeneratedImageVariant.scene_id == scene.id,
        )
        .order_by(GeneratedImageVariant.variant_index)
    ).all()
    coverage = timeline_composer.scene_coverage(session, scene)
    return {
        "scene_id": scene.id,
        "variants": [
            {
                "id": item.id,
                "variant_index": item.variant_index,
                "path": item.path,
                "prompt": item.prompt,
                "negative_prompt": item.negative_prompt,
                "seed": item.seed,
                "width": item.width,
                "height": item.height,
                "status": item.status,
                "error_message": item.error_message,
                "selected": bool(item.media_file_id and item.media_file_id in assigned_media_ids),
            }
            for item in variants
        ],
        "assignments": assignment_values,
        "coverage": {
            "covered_ms": coverage["covered_ms"],
            "duration_ms": coverage["duration_ms"],
            "remaining_ms": coverage["remaining_ms"],
            "complete": coverage["complete"],
        },
    }


def assign_generated_variant(
    session: Session, project: Project, scene_id: str, variant_id: str
) -> dict:
    scene = _scene(session, project, scene_id)
    _assert_visual_editable(scene)
    variant = session.get(GeneratedImageVariant, variant_id)
    if not variant or variant.project_id != project.id or variant.scene_id != scene.id:
        raise LookupError("Image candidate not found")
    if variant.status != "completed" or not variant.media_file_id:
        raise ValueError("Image candidate is not ready")
    media = session.get(MediaFile, variant.media_file_id)
    shot = session.exec(
        select(MediaShot).where(MediaShot.media_file_id == variant.media_file_id)
    ).first()
    if not media or not shot or not Path(media.path).is_file():
        raise ValueError("Image candidate file is missing")
    session.exec(delete(SceneAssignment).where(SceneAssignment.scene_id == scene.id))
    duration_ms = scene.end_ms - scene.start_ms
    assignment = SceneAssignment(
        id=f"assignment_{uuid.uuid4().hex}",
        project_id=project.id,
        scene_id=scene.id,
        media_shot_id=shot.id,
        sequence_index=1,
        scene_offset_start_ms=0,
        scene_offset_end_ms=duration_ms,
        display_duration_ms=duration_ms,
        selection_stage="generated_image",
    )
    session.add(assignment)
    session.commit()
    invalidate_scene_outputs(project, scene)
    return scene_assets(session, project, scene.id)


def clear_scene_assignments(session: Session, project: Project, scene_id: str) -> dict:
    scene = _scene(session, project, scene_id)
    _assert_visual_editable(scene)
    session.exec(delete(SceneAssignment).where(SceneAssignment.scene_id == scene.id))
    session.commit()
    invalidate_scene_outputs(project, scene)
    return scene_assets(session, project, scene.id)


def invalidate_scene_outputs(project: Project, scene: VisualScene) -> None:
    base = get_project_work_dir(project, get_settings().workspace_dir)
    scene_path = base / "renders" / "scenes" / f"scene_{scene.scene_index:04d}.mp4"
    scene_path.unlink(missing_ok=True)
    manifest_path = base / "renders" / "scenes" / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        manifest = {}
    if isinstance(manifest, dict) and manifest.pop(scene.id, None) is not None:
        write_json_atomic(manifest_path, manifest)
    for path in (
        base / "renders" / "visual_track.mp4",
        base / "reports" / "visual_track_report.json",
        base / "reports" / "quality_report.json",
        base / "reports" / "qa.json",
        get_final_video_path(project, get_settings().workspace_dir),
    ):
        path.unlink(missing_ok=True)


def _scene(session: Session, project: Project, scene_id: str) -> VisualScene:
    scene = session.get(VisualScene, scene_id)
    if not scene or scene.project_id != project.id:
        raise LookupError("Scene not found")
    return scene


def _assert_visual_editable(scene: VisualScene) -> None:
    if scene.locked_visual:
        raise ValueError("Scene visual is locked")


def _assignment_value(assignment: SceneAssignment, shot: MediaShot, media: MediaFile) -> dict:
    return {
        "id": assignment.id,
        "media_shot_id": shot.id,
        "media_file_id": media.id,
        "path": media.path,
        "media_type": media.media_type,
        "sequence_index": assignment.sequence_index,
        "start_ms": assignment.scene_offset_start_ms,
        "end_ms": assignment.scene_offset_end_ms,
        "motion_type": assignment.motion_type,
        "transition": assignment.transition,
    }
