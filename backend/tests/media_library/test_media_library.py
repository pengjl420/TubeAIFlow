import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine, select

from app.models.media import MediaFile, MediaShot, SceneAssignment
from app.models.project import Project
from app.models.storyboard import VisualScene
from app.schemas.media import SceneAssignmentRequest
from app.schemas.storyboard import StoryboardContent
from app.services.media_library import ingestion_service, retrieval_service


class MediaLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.engine = create_engine(
            f"sqlite:///{self.root / 'media.db'}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_import_directory_deduplicates_files_and_creates_fixed_interval_shots(self) -> None:
        media_dir = self.root / "source"
        media_dir.mkdir()
        (media_dir / "airport_traveler.mp4").write_bytes(b"same-video")
        (media_dir / "duplicate.mp4").write_bytes(b"same-video")
        metadata = {
            "duration_ms": 25_000,
            "width": 1920,
            "height": 1080,
            "codec_name": "h264",
            "frame_rate": "30/1",
            "format_name": "mov,mp4",
        }

        with Session(self.engine) as session:
            with patch.object(ingestion_service, "probe_media", return_value=metadata):
                result = ingestion_service.import_directory(session, str(media_dir))
            media_file = session.exec(select(MediaFile)).one()
            shots = session.exec(
                select(MediaShot).where(MediaShot.media_file_id == media_file.id)
            ).all()

        self.assertEqual(result["discovered"], 2)
        self.assertEqual(len(result["imported"]), 1)
        self.assertEqual(len(result["skipped"]), 1)
        self.assertEqual([(shot.start_ms, shot.end_ms) for shot in shots], [(0, 12_000), (12_000, 25_000)])

    def test_scene_search_ranks_local_shots_and_persists_manual_assignment(self) -> None:
        storyboard = StoryboardContent(
            visual_summary="A traveler arriving at a 1990s international airport",
            visual_type="historical_reconstruction",
            entities=["traveler"],
            locations=["airport"],
            time_period="1990s",
            scene_category="travel",
            mood="curious",
            shot_preference="wide_or_medium",
            primary_query="1990s airport traveler arrival",
            alternative_queries=["international airport traveler"],
            fallback_category="travel",
            fallback_mood="neutral",
            must_include=["airport"],
            avoid=["smartphone"],
            confidence=0.9,
        )
        project = Project(id="p1", name="Project")
        scene = VisualScene(
            id="p1:scene_0001",
            project_id=project.id,
            scene_index=1,
            start_ms=0,
            end_ms=8000,
            narration="A traveler arrived at the airport.",
            subtitle_ids_json='["p1:sub_0001"]',
            storyboard_json=storyboard.model_dump_json(),
            status="generated",
        )
        good_file = MediaFile(
            id="media-good",
            path=str(self.root / "1990s_airport_traveler.mp4"),
            filename="1990s_airport_traveler.mp4",
            media_type="video",
            file_hash="good",
            duration_ms=10_000,
            width=1920,
            height=1080,
        )
        bad_file = MediaFile(
            id="media-bad",
            path=str(self.root / "modern_smartphone.mp4"),
            filename="modern_smartphone.mp4",
            media_type="video",
            file_hash="bad",
            duration_ms=10_000,
            width=1920,
            height=1080,
        )
        good_shot = MediaShot(
            id="shot-good",
            media_file_id=good_file.id,
            shot_index=1,
            start_ms=0,
            end_ms=10_000,
            description="1990s airport traveler arrival",
            tags_json=json.dumps(["1990s", "airport", "traveler", "arrival"]),
        )
        bad_shot = MediaShot(
            id="shot-bad",
            media_file_id=bad_file.id,
            shot_index=1,
            start_ms=0,
            end_ms=10_000,
            description="modern smartphone closeup",
            tags_json=json.dumps(["modern", "smartphone"]),
        )
        good_shot_id = good_shot.id

        with Session(self.engine) as session:
            session.add_all([project, scene, good_file, bad_file, good_shot, bad_shot])
            session.commit()

            result = retrieval_service.search_scene_candidates(session, project, scene.id)
            self.assertEqual(result["status"], "QUALIFIED")
            self.assertEqual(result["candidates"][0]["media_shot_id"], good_shot_id)
            self.assertEqual(result["candidates"][0]["status"], "QUALIFIED")
            self.assertTrue(result["candidates"][1]["conflicts"])

            assignment = retrieval_service.assign_candidate(
                session,
                project,
                scene.id,
                SceneAssignmentRequest(candidate_id=result["candidates"][0]["id"]),
            )
            saved_scene = session.get(VisualScene, scene.id)
            saved_assignment = session.exec(select(SceneAssignment)).one()

            repeated = retrieval_service.search_scene_candidates(session, project, scene.id)
            repeated_ids = [item["id"] for item in repeated["candidates"]]
            assignment_confirmed = saved_assignment.manual_confirmed
            scene_status = saved_scene.status

        self.assertEqual(assignment["media_shot_id"], good_shot_id)
        self.assertTrue(assignment_confirmed)
        self.assertEqual(scene_status, "assigned")
        self.assertEqual(repeated_ids.count(assignment["candidate_id"]), 1)


if __name__ == "__main__":
    unittest.main()
