import json
import tempfile
import unittest
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
from app.models.visual_style import StyleAsset, StyleAssetMatch
from app.schemas.storyboard import StoryboardContent
from app.services.image_generation import image_generation_service


class ImageGenerationServiceTests(unittest.TestCase):
    def test_regeneration_seed_changes_between_requests_but_is_stable_for_retry(self) -> None:
        first = image_generation_service._regeneration_seed("p", "s", 1, "job-1")
        retry = image_generation_service._regeneration_seed("p", "s", 1, "job-1")
        next_request = image_generation_service._regeneration_seed("p", "s", 1, "job-2")

        self.assertEqual(first, retry)
        self.assertNotEqual(first, next_request)

    def test_flash_provider_resolves_official_model_metadata(self) -> None:
        project = Project(
            id="project-flash",
            name="Flash",
            output_dir=".",
            config_json='{"image_provider_id":"image.seedream_5_flash"}',
        )
        settings = SimpleNamespace(image_generation_provider_id="image.seedream_5")

        with patch.object(image_generation_service, "get_settings", return_value=settings):
            provider_id = image_generation_service._provider_id(project)

        provider = image_generation_service.provider_registry.get(provider_id)
        self.assertEqual(provider_id, "image.seedream_5_flash")
        self.assertEqual(provider.model_id, "doubao-seedream-5-0-flash-260915")

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.engine = create_engine(f"sqlite:///{self.root / 'test.db'}")
        SQLModel.metadata.create_all(self.engine)
        self.settings = SimpleNamespace(
            workspace_dir=self.root,
            image_generation_candidates_per_scene=2,
            image_generation_negative_prompt="text, watermark",
            image_generation_provider_id="image.seedream_5",
            seedream_api_key="secret",
        )

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temporary.cleanup()

    def test_generates_project_scoped_candidates_and_resumes(self) -> None:
        with Session(self.engine) as session:
            project, scene = self._project_scene(session)

            def fake_batch(request):
                results = []
                for job in request.jobs:
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
                request.result_path.write_text(json.dumps(results), encoding="utf-8")

            with (
                patch.object(image_generation_service, "get_settings", return_value=self.settings),
                patch.object(
                    image_generation_service,
                    "_runtime",
                    return_value=SimpleNamespace(generate_batch=fake_batch),
                ) as runner,
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
            self.assertTrue(
                all(item.library_role == LIBRARY_ROLE_PROJECT_GENERATED for item in media_files)
            )
            self.assertTrue(
                all(item.library_role == LIBRARY_ROLE_PROJECT_GENERATED for item in shots)
            )

    def test_recovers_completed_child_results_after_parent_interruption(self) -> None:
        with Session(self.engine) as session:
            project, _scene = self._project_scene(session)

            def fake_batch(request):
                results = []
                for job in request.jobs:
                    output = Path(job["output_path"])
                    output.parent.mkdir(parents=True, exist_ok=True)
                    Image.new("RGB", (job["width"], job["height"]), (40, 50, 60)).save(output)
                    results.append(
                        {
                            "variant_id": job["variant_id"],
                            "status": "completed",
                            "generation_seconds": 1.5,
                        }
                    )
                request.result_path.write_text(json.dumps(results), encoding="utf-8")

            with (
                patch.object(image_generation_service, "get_settings", return_value=self.settings),
                patch.object(
                    image_generation_service,
                    "_runtime",
                    return_value=SimpleNamespace(generate_batch=fake_batch),
                ) as runner,
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

    def test_reuses_approved_style_asset_before_calling_cloud_provider(self) -> None:
        with Session(self.engine) as session:
            first_project, _ = self._project_scene(session, project_id="project-1", name="First")

            def fake_batch(request):
                results = []
                for job in request.jobs:
                    output = Path(job["output_path"])
                    output.parent.mkdir(parents=True, exist_ok=True)
                    Image.new("RGB", (job["width"], job["height"]), (30, 40, 50)).save(output)
                    results.append({"variant_id": job["variant_id"], "status": "completed"})
                request.result_path.write_text(json.dumps(results), encoding="utf-8")

            with (
                patch.object(image_generation_service, "get_settings", return_value=self.settings),
                patch.object(
                    image_generation_service,
                    "_runtime",
                    return_value=SimpleNamespace(generate_batch=fake_batch),
                ),
            ):
                image_generation_service.generate_project_images(session, first_project)

            second_project, _ = self._project_scene(
                session, project_id="project-2", scene_id="scene-2", name="Second"
            )
            with (
                patch.object(image_generation_service, "get_settings", return_value=self.settings),
                patch.object(image_generation_service, "_runtime") as runtime,
            ):
                result = image_generation_service.generate_project_images(session, second_project)

            self.assertEqual(result["generated_count"], 0)
            self.assertEqual(result["reused_count"], 1)
            runtime.assert_not_called()
            self.assertEqual(len(session.exec(select(StyleAsset)).all()), 1)
            audit = session.exec(select(StyleAssetMatch)).one()
            self.assertEqual(audit.project_id, second_project.id)
            self.assertTrue(Path(audit.materialized_path).is_file())

    def test_failed_regeneration_keeps_previous_successful_candidates(self) -> None:
        with Session(self.engine) as session:
            project, scene = self._project_scene(session)

            def successful_batch(request):
                results = []
                for job in request.jobs:
                    output = Path(job["output_path"])
                    output.parent.mkdir(parents=True, exist_ok=True)
                    Image.new("RGB", (job["width"], job["height"]), (70, 80, 90)).save(output)
                    results.append({"variant_id": job["variant_id"], "status": "completed"})
                request.result_path.write_text(json.dumps(results), encoding="utf-8")

            def failed_batch(request):
                request.result_path.write_text(
                    json.dumps(
                        [
                            {"variant_id": job["variant_id"], "status": "failed", "error": "boom"}
                            for job in request.jobs
                        ]
                    ),
                    encoding="utf-8",
                )

            with (
                patch.object(image_generation_service, "get_settings", return_value=self.settings),
                patch.object(
                    image_generation_service,
                    "_runtime",
                    return_value=SimpleNamespace(generate_batch=successful_batch),
                ),
            ):
                image_generation_service.generate_project_images(session, project)

            original = list(
                session.exec(
                    select(GeneratedImageVariant).where(
                        GeneratedImageVariant.scene_id == scene.id,
                        GeneratedImageVariant.status == "completed",
                    )
                ).all()
            )
            original_paths = [Path(item.path) for item in original]

            with (
                patch.object(image_generation_service, "get_settings", return_value=self.settings),
                patch.object(
                    image_generation_service,
                    "_runtime",
                    return_value=SimpleNamespace(generate_batch=failed_batch),
                ),
                self.assertRaisesRegex(RuntimeError, "2 个图片候选生成失败"),
            ):
                image_generation_service.regenerate_scene_images(
                    session, project, scene.id, regeneration_id="attempt-1"
                )

            self.assertTrue(all(session.get(GeneratedImageVariant, item.id) for item in original))
            self.assertTrue(all(path.is_file() for path in original_paths))

    def _project_scene(
        self,
        session: Session,
        *,
        project_id: str = "project-1",
        scene_id: str = "scene-1",
        name: str = "Generated",
    ):
        project = Project(id=project_id, name=name, output_dir=str(self.root))
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
            id=scene_id,
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
