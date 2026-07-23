import json
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.media import (
    LIBRARY_ROLE_PROJECT_GENERATED,
    GeneratedImageVariant,
    MediaFile,
    MediaShot,
)
from app.models.project import Project
from app.models.storyboard import VisualScene
from app.schemas.storyboard import StoryboardContent
from app.services.image_generation import image_generation_service


class ImageGenerationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.model_path = self.root / "juggernautXL_ragnarok.safetensors"
        self.model_path.write_bytes(b"checkpoint")
        self.config_dir = self.root / "diffusers_config"
        self.config_dir.mkdir()
        (self.config_dir / "model_index.json").write_text("{}", encoding="utf-8")
        self.engine = create_engine(f"sqlite:///{self.root / 'test.db'}")
        SQLModel.metadata.create_all(self.engine)
        self.settings = SimpleNamespace(
            workspace_dir=self.root,
            image_generation_model_path=self.model_path,
            image_generation_config_dir=self.config_dir,
            image_generation_python=Path(__import__("sys").executable),
            image_generation_device="cuda:0",
            image_generation_dtype="float16",
            image_generation_width=1024,
            image_generation_height=576,
            image_generation_steps=20,
            image_generation_guidance_scale=5.0,
            image_generation_candidates_per_scene=2,
            image_generation_cpu_offload=True,
            image_generation_negative_prompt="text, watermark",
        )

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temporary.cleanup()

    def test_generates_project_scoped_candidates_and_resumes(self) -> None:
        with Session(self.engine) as session:
            project, scene = self._project_scene(session)

            def fake_batch(_project, _python, _model, _config, batch_path, result_path, *_args):
                results = []
                for job in json.loads(batch_path.read_text(encoding="utf-8")):
                    output = Path(job["output_path"])
                    output.parent.mkdir(parents=True, exist_ok=True)
                    Image.new("RGB", (job["width"], job["height"]), (20, 30, 40)).save(output)
                    results.append(
                        {
                            "variant_id": job["variant_id"],
                            "output_path": str(output),
                            "status": "completed",
                            "generation_seconds": 1.25,
                        }
                    )
                result_path.write_text(json.dumps(results), encoding="utf-8")

            with (
                patch.object(image_generation_service, "get_settings", return_value=self.settings),
                patch.object(image_generation_service.gpu_resource, "exclusive_gpu", return_value=nullcontext()),
                patch.object(image_generation_service, "_run_batch", side_effect=fake_batch) as runner,
            ):
                first = image_generation_service.generate_project_images(session, project)
                second = image_generation_service.generate_project_images(session, project)

            self.assertEqual(first["generated_count"], 2)
            self.assertEqual(second["generated_count"], 0)
            self.assertEqual(runner.call_count, 1)
            variants = session.exec(select(GeneratedImageVariant)).all()
            media_files = session.exec(select(MediaFile)).all()
            shots = session.exec(select(MediaShot)).all()
            self.assertEqual(len(variants), 2)
            self.assertEqual(len(media_files), 1)  # identical fake images deduplicate by hash
            self.assertTrue(all(item.status == "completed" for item in variants))
            self.assertTrue(all(item.library_role == LIBRARY_ROLE_PROJECT_GENERATED for item in media_files))
            self.assertTrue(all(item.library_role == LIBRARY_ROLE_PROJECT_GENERATED for item in shots))

    def test_recovers_completed_child_results_after_parent_interruption(self) -> None:
        with Session(self.engine) as session:
            project, _scene = self._project_scene(session)

            def fake_batch(_project, _python, _model, _config, batch_path, result_path, *_args):
                results = []
                for job in json.loads(batch_path.read_text(encoding="utf-8")):
                    output = Path(job["output_path"])
                    output.parent.mkdir(parents=True, exist_ok=True)
                    Image.new("RGB", (job["width"], job["height"]), (40, 50, 60)).save(output)
                    results.append({
                        "variant_id": job["variant_id"],
                        "status": "completed",
                        "generation_seconds": 1.5,
                    })
                result_path.write_text(json.dumps(results), encoding="utf-8")

            with (
                patch.object(image_generation_service, "get_settings", return_value=self.settings),
                patch.object(image_generation_service.gpu_resource, "exclusive_gpu", return_value=nullcontext()),
                patch.object(image_generation_service, "_run_batch", side_effect=fake_batch) as runner,
            ):
                image_generation_service.generate_project_images(session, project)
                for variant in session.exec(select(GeneratedImageVariant)).all():
                    variant.status = "pending"
                    variant.generation_seconds = None
                    session.add(variant)
                session.commit()

                resumed = image_generation_service.generate_project_images(session, project)

            self.assertEqual(resumed["generated_count"], 0)
            self.assertEqual(runner.call_count, 1)
            variants = session.exec(select(GeneratedImageVariant)).all()
            self.assertTrue(all(item.status == "completed" for item in variants))
            self.assertTrue(all(item.generation_seconds == 1.5 for item in variants))

    def _project_scene(self, session: Session):
        project = Project(id="project-1", name="Generated", output_dir=str(self.root))
        storyboard = StoryboardContent(
            visual_summary="A 1990s Chinese factory at dawn",
            visual_type="historical_reconstruction",
            entities=[],
            locations=["China"],
            time_period="1990s",
            scene_category="business",
            mood="determined",
            shot_preference="wide",
            primary_query="1990s Chinese factory",
            alternative_queries=["industrial factory dawn"],
            fallback_category="business",
            fallback_mood="neutral",
            must_include=["factory"],
            avoid=["smartphone"],
            confidence=0.9,
        )
        scene = VisualScene(
            id="scene-1",
            project_id=project.id,
            scene_index=1,
            start_ms=0,
            end_ms=9000,
            narration="测试旁白",
            storyboard_json=storyboard.model_dump_json(),
        )
        session.add_all([project, scene])
        session.commit()
        return project, scene


if __name__ == "__main__":
    unittest.main()
