import unittest

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.media import GeneratedImageVariant, MediaFile, MediaShot, SceneAssignment
from app.models.project import Project
from app.models.storyboard import VisualScene
from app.services.image_generation import image_assignment_service


class ImageAssignmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        SQLModel.metadata.create_all(self.engine)

    def test_first_generated_image_is_assigned_without_review_or_scoring(self) -> None:
        with Session(self.engine) as session:
            project = Project(id="p1", name="Project")
            scene = VisualScene(id="s1", project_id="p1", scene_index=1, start_ms=0, end_ms=4000, narration="n")
            media = MediaFile(id="m1", path="image.png", filename="image.png", media_type="image", file_hash="hash")
            shot = MediaShot(id="shot1", media_file_id="m1", shot_index=1)
            variant = GeneratedImageVariant(id="v1", project_id="p1", scene_id="s1", variant_index=1, path="image.png", prompt="p", model_path="model", input_signature="sig", seed=1, width=1024, height=576, steps=20, guidance_scale=5, status="completed", media_file_id="m1")
            session.add_all([project, scene, media, shot, variant])
            session.commit()

            result = image_assignment_service.assign_generated_images(session, project)

            assignment = session.exec(select(SceneAssignment)).one()
            self.assertEqual(result["scene_count"], 1)
            self.assertEqual(assignment.media_shot_id, shot.id)
            self.assertEqual(assignment.selection_stage, "generated_image")
            self.assertEqual(assignment.scene_offset_end_ms, 4000)


if __name__ == "__main__":
    unittest.main()
