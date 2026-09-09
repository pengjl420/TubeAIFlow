import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

from app.models.media import GeneratedImageVariant, MediaFile, MediaShot
from app.models.project import Project
from app.models.storyboard import VisualScene
from app.services.storyboard import scene_workspace_service


class SceneWorkspaceServiceTests(unittest.TestCase):
    def test_select_and_clear_generated_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine = create_engine(f"sqlite:///{root / 'workspace.db'}")
            SQLModel.metadata.create_all(engine)
            image_path = root / "candidate.png"
            image_path.write_bytes(b"image")
            with Session(engine) as session:
                project = Project(id="p1", name="Project")
                scene = VisualScene(
                    id="s1", project_id="p1", scene_index=1,
                    start_ms=0, end_ms=5000, narration="Narration",
                )
                media = MediaFile(
                    id="m1", path=str(image_path), filename=image_path.name,
                    media_type="image", file_hash="hash", width=1920, height=1080,
                )
                shot = MediaShot(id="shot1", media_file_id="m1", shot_index=1)
                variant = GeneratedImageVariant(
                    id="v1", project_id="p1", scene_id="s1", variant_index=1,
                    path=str(image_path), prompt="prompt", model_path="model",
                    input_signature="signature", seed=1, width=1920, height=1080,
                    steps=20, guidance_scale=5, status="completed", media_file_id="m1",
                )
                session.add(project)
                session.add(scene)
                session.add(media)
                session.add(shot)
                session.add(variant)
                session.commit()
                settings = SimpleNamespace(workspace_dir=root)
                with patch.object(scene_workspace_service, "get_settings", return_value=settings):
                    selected = scene_workspace_service.assign_generated_variant(
                        session, project, "s1", "v1"
                    )
                    cleared = scene_workspace_service.clear_scene_assignments(
                        session, project, "s1"
                    )

                self.assertTrue(selected["variants"][0]["selected"])
                self.assertTrue(selected["coverage"]["complete"])
                self.assertEqual(len(selected["assignments"]), 1)
                self.assertFalse(cleared["variants"][0]["selected"])
                self.assertFalse(cleared["coverage"]["complete"])
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
