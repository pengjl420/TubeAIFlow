import unittest
from unittest.mock import patch

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models.visual_style import VisualStyleProfile
from app.services.visual_styles import style_service


class VisualStyleServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_builtin_styles_are_published_and_idempotent(self) -> None:
        style_service.ensure_builtin_styles(self.session)
        style_service.ensure_builtin_styles(self.session)
        values = style_service.list_profiles(self.session)
        self.assertEqual(len([item for item in values if item["builtin_key"]]), 2)
        self.assertTrue(all(item["current_revision"] for item in values))

    def test_publish_is_immutable_and_next_edit_creates_new_draft(self) -> None:
        created = style_service.create_profile(
            self.session,
            name="Editorial",
            description="test",
            tags=["documentary"],
            style_prompt="restrained editorial illustration",
            negative_prompt="watermark",
        )
        profile = self.session.get(VisualStyleProfile, created["id"])
        published = style_service.publish_draft(self.session, profile)
        first_revision = published["current_revision"]
        updated = style_service.update_draft(
            self.session,
            profile,
            name="Editorial",
            description="test",
            tags=["documentary"],
            style_prompt="restrained editorial illustration with paper texture",
            negative_prompt="watermark",
            continuity_rules=["keep the same medium"],
            composition_rules=["16:9 landscape"],
            motion_preset={"type": "slow_push"},
        )
        self.assertEqual(first_revision["status"], "published")
        self.assertEqual(updated["draft_revision"]["version"], 2)
        self.assertEqual(updated["current_revision"]["id"], first_revision["id"])

    def test_compile_keeps_style_scene_and_motion_separate(self) -> None:
        created = style_service.create_profile(
            self.session,
            name="Ink",
            description="",
            tags=[],
            style_prompt="monochrome ink wash",
            negative_prompt="watermark, logo",
        )
        revision = style_service.get_revision(
            self.session, created["draft_revision"]["id"]
        )
        compiled = style_service.compile_revision(
            revision,
            "A historian opens an archive box",
            "logo, extra fingers",
            "random text",
        )
        self.assertIn("monochrome ink wash", compiled["image_prompt"])
        self.assertIn("A historian opens an archive box", compiled["image_prompt"])
        self.assertEqual(compiled["negative_prompt"].count("logo"), 1)
        self.assertEqual(compiled["motion_directive"]["type"], "slow_push")

    def test_deepseek_optimization_is_returned_as_a_suggestion(self) -> None:
        response = {
            "optimized_style_prompt": "cohesive paper-cut illustration",
            "optimized_negative_prompt": "watermark",
            "continuity_rules": ["keep palette stable"],
            "composition_rules": ["16:9"],
            "warnings": [],
            "summary": "normalized",
        }
        with patch.object(style_service.DeepSeekClient, "chat_json", return_value=response):
            result = style_service.optimize_prompt("paper cut", "", "consistency")
        self.assertEqual(result, response)


if __name__ == "__main__":
    unittest.main()
