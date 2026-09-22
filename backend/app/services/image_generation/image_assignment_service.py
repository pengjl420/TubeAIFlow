from __future__ import annotations

import json
import uuid

from sqlmodel import Session, select

from app.models.media import GeneratedImageVariant, MediaShot, SceneAssignment
from app.models.project import Project
from app.models.storyboard import VisualScene
from app.config import get_settings
from app.infrastructure.project_layout import get_project_work_dir
from app.services.rendering import timeline_composer


def assign_generated_images(session: Session, project: Project) -> dict:
    scenes = list(
        session.exec(
            select(VisualScene)
            .where(VisualScene.project_id == project.id)
            .order_by(VisualScene.scene_index)
        ).all()
    )
    assigned = [assign_scene_image(session, project, scene.id) for scene in scenes]
    return {"project_id": project.id, "scene_count": len(scenes), "assignments": assigned}


def assign_scene_image(session: Session, project: Project, scene_id: str) -> dict:
    scene = session.get(VisualScene, scene_id)
    if not scene or scene.project_id != project.id:
        raise ValueError("Visual scene does not exist")
    existing = timeline_composer.scene_assignments(session, scene.id)
    if existing:
        return {"scene_id": scene.id, "assignment_id": existing[0].id, "reused": True}

    beat_assignments = _assign_visual_beats(session, project, scene)
    if beat_assignments:
        session.add_all(beat_assignments)
        session.commit()
        return {
            "scene_id": scene.id,
            "assignment_id": beat_assignments[0].id,
            "assignment_ids": [item.id for item in beat_assignments],
            "reused": False,
        }

    variant = session.exec(
        select(GeneratedImageVariant)
        .where(
            GeneratedImageVariant.project_id == project.id,
            GeneratedImageVariant.scene_id == scene.id,
            GeneratedImageVariant.status == "completed",
        )
        .order_by(GeneratedImageVariant.variant_index)
    ).first()
    if not variant or not variant.media_file_id:
        raise RuntimeError(f"Scene {scene.scene_index} has no generated image")
    shot = session.exec(
        select(MediaShot).where(MediaShot.media_file_id == variant.media_file_id)
    ).first()
    if not shot:
        raise RuntimeError(f"Scene {scene.scene_index} generated image is not registered")

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
    return {"scene_id": scene.id, "assignment_id": assignment.id, "reused": False}


def _assign_visual_beats(
    session: Session, project: Project, scene: VisualScene
) -> list[SceneAssignment]:
    plan_path = (
        get_project_work_dir(project, get_settings().workspace_dir)
        / "work"
        / "04_plan"
        / "visual_plan.json"
    )
    try:
        payload = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    visuals = [
        item
        for item in payload.get("visuals", [])
        if isinstance(item, dict)
        and item.get("scene_id") == scene.id
        and item.get("visual_beat_id")
    ] if isinstance(payload, dict) else []
    if not visuals:
        return []
    variants = list(
        session.exec(
            select(GeneratedImageVariant).where(
                GeneratedImageVariant.project_id == project.id,
                GeneratedImageVariant.scene_id == scene.id,
                GeneratedImageVariant.status == "completed",
            )
        ).all()
    )
    variants_by_beat = {
        variant.visual_beat_id: variant
        for variant in variants
        if variant.visual_beat_id and variant.media_file_id
    }
    if any(str(item["visual_beat_id"]) not in variants_by_beat for item in visuals):
        return []
    assignments: list[SceneAssignment] = []
    for index, visual in enumerate(sorted(visuals, key=lambda item: int(item["start_ms"])), 1):
        variant = variants_by_beat[str(visual["visual_beat_id"])]
        shot = session.exec(
            select(MediaShot).where(MediaShot.media_file_id == variant.media_file_id)
        ).first()
        if not shot:
            return []
        start_ms = max(0, int(visual["start_ms"]) - scene.start_ms)
        end_ms = min(scene.end_ms - scene.start_ms, int(visual["end_ms"]) - scene.start_ms)
        assignments.append(
            SceneAssignment(
                id=f"assignment_{uuid.uuid4().hex}",
                project_id=project.id,
                scene_id=scene.id,
                visual_beat_id=str(visual["visual_beat_id"]),
                media_shot_id=shot.id,
                sequence_index=index,
                scene_offset_start_ms=start_ms,
                scene_offset_end_ms=end_ms,
                display_duration_ms=end_ms - start_ms,
                selection_stage="generated_image",
                motion_type="anime_master_kenburns",
            )
        )
    return assignments
