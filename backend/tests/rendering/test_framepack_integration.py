import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from sqlmodel import Session, SQLModel, create_engine

from app.config import Settings
from app.integrations.framepack.client import FramePackClient, FramePackUnavailableError
from app.models.media import MediaFile, MediaShot, SceneAssignment
from app.models.project import Project
from app.models.storyboard import VisualScene
from app.schemas.storyboard import StoryboardContent
from app.services.rendering import scene_renderer, scene_router
from framepack_worker.engine import _framepack_frame_count


class FramePackIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.engine = create_engine(
            f"sqlite:///{self.root / 'test.db'}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temp.cleanup()

    def test_project_router_limits_automatic_framepack_ratio(self) -> None:
        with Session(self.engine) as session:
            assignments = {}
            scenes = []
            for index in range(10):
                scene, assignment = self._eligible_scene(session, index)
                scenes.append(scene)
                assignments[scene.id] = [assignment]
            settings = Settings(
                workspace_dir=self.root,
                framepack_enabled=True,
                framepack_max_ratio=0.2,
            )

            routes = scene_router.route_project_scenes(
                session, scenes, assignments, settings
            )

            self.assertEqual(
                sum(route.provider == "framepack" for route in routes.values()), 2
            )

    def test_high_identity_risk_forced_scene_stays_on_ffmpeg(self) -> None:
        with Session(self.engine) as session:
            scene, assignment = self._eligible_scene(session, 1, identity_risk=9)
            assignment.render_mode = "framepack"
            settings = Settings(
                workspace_dir=self.root,
                framepack_enabled=True,
                framepack_max_ratio=1,
            )

            route = scene_router.route_single_scene(
                session, scene, [assignment], settings
            )

            self.assertEqual(route.provider, "ffmpeg")
            self.assertIn("风险规则", route.reason)

    def test_framepack_failure_falls_back_to_ffmpeg(self) -> None:
        source = self.root / "source.png"
        source.write_bytes(b"image")
        with Session(self.engine) as session:
            project, scene, assignment = self._scene_with_source(session, source)
            settings = Settings(
                workspace_dir=self.root,
                framepack_enabled=True,
                framepack_max_ratio=1,
            )

            def fake_ffmpeg(args, _project_id):
                Path(args[-1]).write_bytes(b"video")

            quality = {
                "passed": True,
                "metadata": {"duration_ms": 5000},
                "issues": [],
            }
            with (
                patch.object(scene_renderer, "get_settings", return_value=settings),
                patch.object(
                    scene_renderer.framepack_renderer,
                    "render_framepack_scene",
                    side_effect=RuntimeError("CUDA out of memory"),
                ),
                patch.object(scene_renderer, "run_ffmpeg", side_effect=fake_ffmpeg) as ffmpeg,
                patch.object(scene_renderer, "check_scene_video", return_value=quality),
            ):
                result = scene_renderer.render_scene(
                    session,
                    project,
                    scene,
                    assignment,
                    route=scene_router.SceneRoute("framepack", "test"),
                )

            self.assertEqual(result["requested_provider"], "framepack")
            self.assertEqual(result["provider"], "ffmpeg")
            self.assertIn("out of memory", result["fallback_reason"])
            self.assertEqual(ffmpeg.call_count, 1)

    def test_client_reports_unavailable_worker(self) -> None:
        settings = Settings(workspace_dir=self.root)
        client = FramePackClient(settings)
        with patch.object(
            httpx,
            "get",
            side_effect=httpx.ConnectError("offline"),
        ):
            with self.assertRaises(FramePackUnavailableError):
                client.health()

    def test_frame_count_matches_framepack_window_shape(self) -> None:
        frames = _framepack_frame_count(5.0, 30)
        self.assertEqual((frames - 3) % 4, 0)
        self.assertLessEqual(abs(frames - 150), 2)

    def _eligible_scene(
        self, session: Session, index: int, identity_risk: int = 2
    ) -> tuple[VisualScene, SceneAssignment]:
        storyboard = StoryboardContent(
            visual_summary="A worker walking in an office",
            visual_type="documentary",
            scene_category="business",
            mood="focused",
            shot_preference="medium",
            primary_query="office worker walking",
            fallback_category="business",
            fallback_mood="neutral",
            confidence=0.9,
            motion_prompt="The worker walks slowly. The camera gently tracks backward.",
            scene_type="person_walking",
            importance_score=9,
            motion_score=8,
            identity_risk=identity_risk,
            subject_count=1,
        )
        scene = VisualScene(
            id=f"scene-{index}",
            project_id="project-1",
            scene_index=index + 1,
            start_ms=index * 5000,
            end_ms=(index + 1) * 5000,
            narration="test",
            storyboard_json=storyboard.model_dump_json(),
        )
        media = MediaFile(
            id=f"media-{index}",
            path=str(self.root / f"{index}.png"),
            filename=f"{index}.png",
            media_type="image",
            file_hash=f"hash-{index}",
            width=1024,
            height=576,
        )
        shot = MediaShot(
            id=f"shot-{index}", media_file_id=media.id, shot_index=1
        )
        assignment = SceneAssignment(
            id=f"assignment-{index}",
            project_id="project-1",
            scene_id=scene.id,
            media_shot_id=shot.id,
        )
        session.add_all([scene, media, shot, assignment])
        session.commit()
        return scene, assignment

    def _scene_with_source(
        self, session: Session, source: Path
    ) -> tuple[Project, VisualScene, SceneAssignment]:
        project = Project(id="project-1", name="Project", output_dir=str(self.root))
        scene, assignment = self._eligible_scene(session, 20)
        scene.project_id = project.id
        shot = session.get(MediaShot, assignment.media_shot_id)
        media = session.get(MediaFile, shot.media_file_id)
        media.path = str(source)
        assignment.scene_offset_start_ms = 0
        assignment.scene_offset_end_ms = 5000
        assignment.display_duration_ms = 5000
        session.add_all([project, scene, media, assignment])
        session.commit()
        return project, scene, assignment


if __name__ == "__main__":
    unittest.main()

