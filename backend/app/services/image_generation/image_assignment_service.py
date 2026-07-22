from __future__ import annotations

import uuid

from sqlmodel import Session, select

from app.models.media import GeneratedImageVariant, MediaShot, SceneAssignment
from app.models.project import Project
from app.models.storyboard import VisualScene
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
    shot = session.exec(select(MediaShot).where(MediaShot.media_file_id == variant.media_file_id)).first()
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
