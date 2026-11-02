import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.visual_style import StyleAsset, StyleAssetMatch, VisualStyleProfile, VisualStyleRevision
from app.schemas.storyboard import StoryboardContent
from app.services.visual_styles import style_asset_service


class StyleAssetServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.engine = create_engine(f"sqlite:///{self.root / 'test.db'}")
        SQLModel.metadata.create_all(self.engine)
        self.settings_patch = patch.object(
            style_asset_service,
            "get_settings",
            return_value=SimpleNamespace(workspace_dir=self.root),
        )
        self.settings_patch.start()
        with Session(self.engine) as session:
            session.add(VisualStyleProfile(id="style", name="Style"))
            session.add(
                VisualStyleRevision(
                    id="revision",
                    style_profile_id="style",
                    version=1,
                    style_prompt="documentary",
                    content_hash="hash",
                )
            )
            session.commit()

    def tearDown(self) -> None:
        self.settings_patch.stop()
        self.engine.dispose()
        self.temporary.cleanup()

    def test_revision_scoped_archive_deduplicates_and_matches_safe_storyboard(self) -> None:
        source = self.root / "source.png"
        Image.new("RGB", (160, 90), (20, 30, 40)).save(source)
        storyboard = self._storyboard()
        with Session(self.engine) as session:
            revision = session.get(VisualStyleRevision, "revision")
            first = style_asset_service._archive(
                session,
                revision=revision,
                source=source,
                source_type="project_generation",
                prompt="factory",
                negative_prompt="watermark",
                query_text=style_asset_service.storyboard_query(storyboard),
                provider_id="image.seedream_5",
                model_id="model",
                status="approved",
                entities=storyboard.entities,
                locations=storyboard.locations,
            )
            second = style_asset_service._archive(
                session,
                revision=revision,
                source=source,
                source_type="project_generation",
                prompt="factory",
                negative_prompt="watermark",
                query_text=style_asset_service.storyboard_query(storyboard),
                provider_id="image.seedream_5",
                model_id="model",
                status="approved",
            )
            session.commit()
            match = style_asset_service.find_reusable_asset(
                session,
                style_revision_id="revision",
                storyboard=storyboard,
                width=160,
                height=90,
            )

            self.assertEqual(first.id, second.id)
            self.assertEqual(len(session.exec(select(StyleAsset)).all()), 1)
            self.assertIsNotNone(match)
            self.assertEqual(match[0].id, first.id)
            self.assertGreaterEqual(match[1], style_asset_service.AUTO_REUSE_THRESHOLD)
            self.assertIn("revisions", Path(first.path).parts)

    def test_high_fact_risk_is_not_auto_reused(self) -> None:
        storyboard = self._storyboard(fact_risk="high")
        with Session(self.engine) as session:
            self.assertIsNone(
                style_asset_service.find_reusable_asset(
                    session,
                    style_revision_id="revision",
                    storyboard=storyboard,
                    width=160,
                    height=90,
                )
            )

    def test_materialize_records_auditable_match(self) -> None:
        source = self.root / "source.png"
        destination = self.root / "project" / "candidate.png"
        Image.new("RGB", (160, 90)).save(source)
        with Session(self.engine) as session:
            revision = session.get(VisualStyleRevision, "revision")
            asset = style_asset_service._archive(
                session,
                revision=revision,
                source=source,
                source_type="project_generation",
                prompt="factory",
                negative_prompt="",
                query_text="factory dawn",
                provider_id="image.seedream_5",
                model_id="model",
                status="approved",
            )
            project = SimpleNamespace(id="project")
            style_asset_service.materialize_reuse(
                session,
                asset=asset,
                project=project,
                scene_id="scene",
                query_text="factory dawn",
                score=1.0,
                destination=destination,
            )
            session.commit()

            audit = session.exec(select(StyleAssetMatch)).one()
            self.assertTrue(destination.is_file())
            self.assertEqual(audit.decision, "auto_reused")
            self.assertEqual(session.get(StyleAsset, asset.id).usage_count, 1)

    @staticmethod
    def _storyboard(*, fact_risk: str = "low") -> StoryboardContent:
        return StoryboardContent(
            visual_summary="A 1990s Chinese factory at dawn",
            visual_type="historical_reconstruction",
            entities=[],
            locations=["China"],
            time_period="1990s",
            scene_category="business",
            mood="determined",
            shot_preference="wide",
            primary_query="1990s Chinese factory",
            fallback_category="business",
            fallback_mood="neutral",
            must_include=["factory"],
            confidence=0.9,
            identity_risk=3,
            fact_risk=fact_risk,
        )


if __name__ == "__main__":
    unittest.main()
