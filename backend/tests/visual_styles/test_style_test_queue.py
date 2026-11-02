import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.visual_style import StyleAsset, StyleTestRun, VisualStyleProfile, VisualStyleRevision
from app.services.visual_styles import style_asset_service, style_service, style_test_queue


class StyleTestQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.engine_patch = patch.object(style_test_queue, "engine", self.engine)
        self.engine_patch.start()
        self.asset_settings_patch = patch.object(
            style_asset_service,
            "get_settings",
            return_value=SimpleNamespace(workspace_dir=self.root),
        )
        self.asset_settings_patch.start()
        with Session(self.engine) as session:
            session.add(VisualStyleProfile(id="style", name="Style"))
            session.add(
                VisualStyleRevision(
                    id="revision",
                    style_profile_id="style",
                    version=1,
                    style_prompt="paper cut",
                    content_hash="hash",
                )
            )
            session.commit()

    def tearDown(self) -> None:
        self.engine_patch.stop()
        self.asset_settings_patch.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def _settings(self):
        return SimpleNamespace(
            workspace_dir=self.root,
            image_generation_provider_id="image.seedream_5",
            image_generation_negative_prompt="watermark",
        )

    def test_enqueue_is_idempotent_for_the_same_client_request(self) -> None:
        provider = SimpleNamespace(id="image.seedream_5", model_id="model")
        with Session(self.engine) as session:
            with (
                patch.object(style_service, "get_settings", return_value=self._settings()),
                patch.object(style_service.provider_registry, "get", return_value=provider),
            ):
                revision = session.get(VisualStyleRevision, "revision")
                first = style_service.enqueue_style_test(
                    session,
                    revision,
                    scene_description="archive room",
                    candidates=1,
                    client_request_id="request-1",
                )
                second = style_service.enqueue_style_test(
                    session,
                    revision,
                    scene_description="archive room",
                    candidates=1,
                    client_request_id="request-1",
                )
                runs = list(session.exec(select(StyleTestRun)).all())

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(runs), 1)

    def test_worker_generates_each_candidate_once_and_persists_progress(self) -> None:
        output = self.root / "candidate.png"
        row = {"index": 1, "status": "queued", "path": str(output)}
        with Session(self.engine) as session:
            session.add(
                StyleTestRun(
                    id="run",
                    client_request_id="request",
                    style_revision_id="revision",
                    candidate_count=1,
                    scene_description="archive room",
                    compiled_prompt="paper cut archive",
                    model_id="model",
                    output_json=json.dumps([row]),
                )
            )
            session.commit()

        def generate(*, prompt, output_path):
            from PIL import Image

            Image.new("RGB", (16, 9)).save(output_path, format="PNG")
            return 12.5

        with patch.object(style_test_queue.SeedreamClient, "generate", side_effect=generate) as call:
            self.assertTrue(style_test_queue.process_next_run())

        with Session(self.engine) as session:
            run = session.get(StyleTestRun, "run")
            candidates = json.loads(run.output_json)
            self.assertEqual(run.status, "completed")
            self.assertEqual(candidates[0]["status"], "completed")
            self.assertTrue(candidates[0]["style_asset_id"])
            self.assertEqual(len(session.exec(select(StyleAsset)).all()), 1)
        self.assertEqual(call.call_count, 1)

    def test_recovery_marks_missing_submitting_result_unknown_without_api_call(self) -> None:
        row = {
            "index": 1,
            "status": "submitting",
            "path": str(self.root / "missing.png"),
        }
        with Session(self.engine) as session:
            session.add(
                StyleTestRun(
                    id="run",
                    style_revision_id="revision",
                    status="running",
                    candidate_count=1,
                    scene_description="archive room",
                    output_json=json.dumps([row]),
                )
            )
            session.commit()
            self.assertEqual(style_test_queue.recover_interrupted_runs(session), 1)
            run = session.get(StyleTestRun, "run")
            self.assertEqual(run.status, "unknown")
            self.assertEqual(json.loads(run.output_json)[0]["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
