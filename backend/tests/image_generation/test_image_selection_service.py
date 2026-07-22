import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.media import (
    LIBRARY_ROLE_PROJECT_GENERATED,
    GeneratedImageVariant,
    MediaFile,
    MediaShot,
    SceneAssignment,
    SceneCandidate,
)
from app.models.project import Project
from app.models.storyboard import VisualScene
from app.schemas.storyboard import StoryboardContent
from app.services.image_generation import image_selection_service


class ImageSelectionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.engine = create_engine(f"sqlite:///{self.root / 'test.db'}")
        SQLModel.metadata.create_all(self.engine)
        self.settings = SimpleNamespace(
            image_selection_semantic_weight=0.7,
            image_selection_technical_weight=0.3,
            image_selection_min_semantic_score=0.2,
            image_selection_min_total_score=0.5,
            image_selection_min_score_margin=0.03,
            image_selection_min_sharpness=0.001,
            image_selection_max_clipped_ratio=0.55,
        )

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temporary.cleanup()

    def test_scores_and_selects_clear_best_candidate(self) -> None:
        with Session(self.engine) as session:
            project, scene = self._project_scene(session)
            first = self._candidate(session, project, scene, 1, self._texture(11))
            second = self._candidate(session, project, scene, 2, self._texture(22))
            scores = {
                Path(first[1].path): (0.78, 0.10),
                Path(second[1].path): (0.55, 0.10),
            }
            with self._patched_runtime(scores):
                result = image_selection_service.score_scene_images(session, project, scene.id)
                selected = image_selection_service.auto_assign_best_image(session, project, scene.id)

            self.assertEqual(result["qualified_count"], 2)
            self.assertTrue(selected["complete"])
            assignment = session.exec(select(SceneAssignment)).one()
            self.assertEqual(assignment.candidate_id, first[0].id)
            self.assertIn("系统综合评分自动选图", assignment.selection_reason)

    def test_close_scores_still_choose_best_candidate_automatically(self) -> None:
        with Session(self.engine) as session:
            project, scene = self._project_scene(session)
            image = self._texture(33)
            first = self._candidate(session, project, scene, 1, image)
            second = self._candidate(session, project, scene, 2, image)
            scores = {
                Path(first[1].path): (0.70, 0.10),
                Path(second[1].path): (0.69, 0.10),
            }
            with self._patched_runtime(scores):
                image_selection_service.score_scene_images(session, project, scene.id)
                selected = image_selection_service.auto_assign_best_image(session, project, scene.id)

            self.assertTrue(selected["complete"])
            assignment = session.exec(select(SceneAssignment)).one()
            self.assertEqual(assignment.candidate_id, first[0].id)

    def test_manual_review_mode_keeps_generated_image_pending(self) -> None:
        with Session(self.engine) as session:
            project, scene = self._project_scene(session)
            candidate, media = self._candidate(session, project, scene, 1, self._texture(44))
            with self._patched_runtime({Path(media.path): (0.82, 0.05)}):
                image_selection_service.score_scene_images(session, project, scene.id)
                image_selection_service.auto_assign_best_image(
                    session, project, scene.id, review_required=True
                )

            assignment = session.exec(select(SceneAssignment)).one()
            self.assertEqual(assignment.candidate_id, candidate.id)
            self.assertFalse(assignment.manual_confirmed)
            self.assertIn("等待人工复核", assignment.selection_reason)

    def test_low_quality_image_is_not_qualified(self) -> None:
        with Session(self.engine) as session:
            project, scene = self._project_scene(session)
            flat = np.full((768, 1344, 3), 128, dtype=np.uint8)
            candidate, media = self._candidate(session, project, scene, 1, flat)
            with self._patched_runtime({Path(media.path): (0.90, 0.05)}):
                image_selection_service.score_scene_images(session, project, scene.id)

            session.refresh(candidate)
            conflicts = json.loads(candidate.conflicts_json)
            self.assertEqual(candidate.status, "LOW_RELEVANCE")
            self.assertTrue(any("清晰度" in item or "对比度" in item for item in conflicts))

    def _patched_runtime(self, scores):
        return _MultiPatch(
            patch.object(image_selection_service, "get_settings", return_value=self.settings),
            patch.object(image_selection_service, "_semantic_scores", return_value=scores),
            patch.object(image_selection_service.embedding, "release_model"),
        )

    def _project_scene(self, session: Session):
        project = Project(id="project-1", name="Generated", output_dir=str(self.root))
        storyboard = StoryboardContent(
            visual_summary="A 1990s Chinese factory at dawn",
            visual_type="historical_reconstruction",
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
            narration="A factory at dawn",
            storyboard_json=storyboard.model_dump_json(),
        )
        session.add_all([project, scene])
        session.commit()
        return project, scene

    def _candidate(self, session, project, scene, index: int, pixels):
        path = self.root / f"candidate_{index:02d}.png"
        Image.fromarray(pixels).save(path)
        media = MediaFile(
            id=f"media-{index}",
            provider="local_image_generation",
            path=str(path),
            filename=path.name,
            media_type="image",
            file_hash=f"hash-{index}",
            size_bytes=path.stat().st_size,
            width=1344,
            height=768,
            library_role=LIBRARY_ROLE_PROJECT_GENERATED,
        )
        shot = MediaShot(
            id=f"shot-{index}",
            media_file_id=media.id,
            shot_index=1,
            library_role=LIBRARY_ROLE_PROJECT_GENERATED,
        )
        candidate = SceneCandidate(
            id=f"candidate-{index}",
            project_id=project.id,
            scene_id=scene.id,
            media_shot_id=shot.id,
            selection_stage="local_generated_image",
            status="QUALIFIED",
        )
        variant = GeneratedImageVariant(
            id=f"variant-{index}",
            project_id=project.id,
            scene_id=scene.id,
            variant_index=index,
            path=str(path),
            prompt="factory",
            model_path="model.safetensors",
            input_signature=f"signature-{index}",
            seed=index,
            width=1344,
            height=768,
            steps=30,
            guidance_scale=5.5,
            status="completed",
            media_file_id=media.id,
            candidate_id=candidate.id,
        )
        session.add_all([media, shot, candidate, variant])
        session.commit()
        return candidate, media

    @staticmethod
    def _texture(seed: int):
        rng = np.random.default_rng(seed)
        base = rng.integers(20, 236, size=(768, 1344, 3), dtype=np.uint8)
        return base


class _MultiPatch:
    def __init__(self, *patchers):
        self.patchers = patchers

    def __enter__(self):
        return [item.start() for item in self.patchers]

    def __exit__(self, exc_type, exc, traceback):
        for item in reversed(self.patchers):
            item.stop()


if __name__ == "__main__":
    unittest.main()
