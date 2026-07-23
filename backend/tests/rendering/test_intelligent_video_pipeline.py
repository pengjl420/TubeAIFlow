import unittest
from unittest.mock import patch

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models.project import Project
from app.models.storyboard import VisualScene
from app.workflows import video_synthesis


class GeneratedImageVideoPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

    def test_removed_semantic_mode_is_rejected(self) -> None:
        with Session(self.engine) as session:
            project = Project(id="p1", name="Project", config_json='{"video_mode":"ai_semantic"}')
            session.add(project)
            session.commit()
            with self.assertRaisesRegex(ValueError, "Unsupported video generation mode"):
                video_synthesis.run_video_synthesis(session, project, "storyboard", lambda _: None)

    def test_generated_images_continue_directly_to_scene_render(self) -> None:
        with Session(self.engine) as session:
            project = Project(id="p1", name="Project", config_json='{"video_mode":"ai_generated_images"}')
            scene = VisualScene(id="scene1", project_id="p1", scene_index=1, start_ms=0, end_ms=1000, narration="n")
            session.add_all([project, scene])
            session.commit()
            changed = []
            with (
                patch.object(video_synthesis, "ensure_ffmpeg_available"),
                patch.object(video_synthesis.image_generation_service, "generate_project_images"),
                patch.object(video_synthesis.image_assignment_service, "assign_generated_images"),
                patch.object(video_synthesis.scene_renderer, "render_all_scenes"),
                patch.object(video_synthesis.visual_track_composer, "compose_visual_track"),
                patch.object(video_synthesis.final_renderer, "compose_final_video"),
                patch.object(video_synthesis.qa_service, "run_quality_check", return_value={"passed": True}),
            ):
                video_synthesis.run_video_synthesis(session, project, "image_generation", changed.append)
            self.assertEqual(changed, ["scene_render", "visual_track", "final_render", "quality_check", "completed"])


if __name__ == "__main__":
    unittest.main()
