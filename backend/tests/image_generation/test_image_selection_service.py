import unittest
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.media import GeneratedImageVariant, MediaFile, MediaShot, SceneAssignment
from app.models.project import Project
from app.models.storyboard import VisualScene
from app.services.image_generation import image_assignment_service
from app.infrastructure.project_layout import get_project_work_dir


class ImageAssignmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        SQLModel.metadata.create_all(self.engine)

    def test_first_generated_image_is_assigned_without_review_or_scoring(self) -> None:
        with Session(self.engine) as session:
            project = Project(id="p1", name="Project")
            scene = VisualScene(
                id="s1", project_id="p1", scene_index=1, start_ms=0, end_ms=4000, narration="n"
            )
            media = MediaFile(
                id="m1",
                path="image.png",
                filename="image.png",
                media_type="image",
                file_hash="hash",
            )
            shot = MediaShot(id="shot1", media_file_id="m1", shot_index=1)
            variant = GeneratedImageVariant(
                id="v1",
                project_id="p1",
                scene_id="s1",
                variant_index=1,
                path="image.png",
                prompt="p",
                model_path="model",
                input_signature="sig",
                seed=1,
                width=1024,
                height=576,
                steps=20,
                guidance_scale=5,
                status="completed",
                media_file_id="m1",
            )
            session.add_all([project, scene, media, shot, variant])
            session.commit()

            result = image_assignment_service.assign_generated_images(session, project)

            assignment = session.exec(select(SceneAssignment)).one()
            self.assertEqual(result["scene_count"], 1)
            self.assertEqual(assignment.media_shot_id, shot.id)
            self.assertEqual(assignment.selection_stage, "generated_image")
            self.assertEqual(assignment.scene_offset_end_ms, 4000)

    def test_anime_visual_beats_create_contiguous_scene_assignments(self) -> None:
        with tempfile.TemporaryDirectory() as directory, Session(self.engine) as session:
            root = Path(directory)
            project = Project(id="p2", name="Anime", output_dir=str(root))
            scene = VisualScene(
                id="s2", project_id="p2", scene_index=1,
                start_ms=10_000, end_ms=30_000, narration="long scene",
            )
            records = [project, scene]
            visuals = []
            for index, (start, end) in enumerate(((10_000, 20_000), (20_000, 30_000))):
                media = MediaFile(
                    id=f"m{index + 2}", path=f"image-{index}.png",
                    filename=f"image-{index}.png", media_type="image", file_hash=f"hash-{index}",
                )
                shot = MediaShot(id=f"shot-{index}", media_file_id=media.id, shot_index=1)
                beat_id = f"s2:beat:{index}"
                variant = GeneratedImageVariant(
                    id=f"v-{index}", project_id=project.id, scene_id=scene.id,
                    visual_beat_id=beat_id, variant_index=index, path=media.path,
                    prompt="prompt", model_path="model", input_signature=f"sig-{index}",
                    seed=index, width=1024, height=576, steps=0, guidance_scale=0,
                    status="completed", media_file_id=media.id,
                )
                records.extend([media, shot, variant])
                visuals.append({
                    "visual_id": f"anime-{index}", "visual_beat_id": beat_id,
                    "scene_id": scene.id, "start_ms": start, "end_ms": end,
                })
            session.add_all(records)
            session.commit()
            work_dir = get_project_work_dir(project, root)
            plan_path = work_dir / "work" / "04_plan" / "visual_plan.json"
            plan_path.parent.mkdir(parents=True)
            plan_path.write_text(json.dumps({"visuals": visuals}), encoding="utf-8")
            with patch.object(
                image_assignment_service, "get_settings",
                return_value=SimpleNamespace(workspace_dir=root),
            ):
                image_assignment_service.assign_generated_images(session, project)

            assignments = list(
                session.exec(select(SceneAssignment).order_by(SceneAssignment.sequence_index)).all()
            )
            self.assertEqual(len(assignments), 2)
            self.assertEqual(
                [(item.scene_offset_start_ms, item.scene_offset_end_ms) for item in assignments],
                [(0, 10_000), (10_000, 20_000)],
            )
            self.assertEqual([item.visual_beat_id for item in assignments], [
                "s2:beat:0", "s2:beat:1",
            ])


if __name__ == "__main__":
    unittest.main()
