import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine, select

from app.models.media import MediaFile, MediaKeyframe, MediaShot, SceneAssignment, SceneCandidate
from app.models.project import Project
from app.models.storyboard import VisualScene
from app.schemas.media import SceneAssignmentRequest
from app.schemas.storyboard import StoryboardContent
from app.services.media_library import fallback_service, ingestion_service, retrieval_service


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

    def test_asset_library_page_filters_searches_and_returns_global_summary(self) -> None:
        files = [
            MediaFile(
                id="media-city",
                path=str(self.root / "city.mp4"),
                filename="city.mp4",
                media_type="video",
                file_hash="city-hash",
                library_role="semantic",
                created_at="2026-01-02T00:00:00Z",
            ),
            MediaFile(
                id="media-mountain",
                path=str(self.root / "mountain.mp4"),
                filename="mountain.mp4",
                media_type="video",
                file_hash="mountain-hash",
                library_role="landscape_fallback",
                fallback_category="landscape",
                mood="calm",
                created_at="2026-01-01T00:00:00Z",
            ),
        ]
        shots = [
            MediaShot(
                id="shot-city",
                media_file_id="media-city",
                shot_index=1,
                vector_id=12,
                technical_json=json.dumps({"vector_model": ingestion_service.MODEL_NAME}),
            ),
            MediaShot(id="shot-mountain", media_file_id="media-mountain", shot_index=1),
        ]

        with Session(self.engine) as session:
            session.add_all([*files, *shots])
            session.commit()
            result = ingestion_service.list_asset_page(
                session,
                page=1,
                page_size=1,
                library_role="landscape_fallback",
                search="mountain",
            )

        self.assertEqual(result["total"], 1)
        self.assertEqual([asset["id"] for asset in result["assets"]], ["media-mountain"])
        self.assertEqual(result["summary"]["asset_count"], 2)
        self.assertEqual(result["summary"]["shot_count"], 2)
        self.assertEqual(result["summary"]["semantic_asset_count"], 1)
        self.assertEqual(result["summary"]["indexed_shot_count"], 1)

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

            conflict_candidate_id = result["candidates"][1]["id"]
            with self.assertRaisesRegex(ValueError, "需要人工确认"):
                retrieval_service.assign_candidate(
                    session,
                    project,
                    scene.id,
                    SceneAssignmentRequest(candidate_id=conflict_candidate_id),
                )
            overridden = retrieval_service.assign_candidate(
                session,
                project,
                scene.id,
                SceneAssignmentRequest(
                    candidate_id=conflict_candidate_id,
                    manual_override=True,
                ),
            )
            override_reason = session.exec(select(SceneAssignment)).one().selection_reason

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
        self.assertEqual(overridden["candidate_id"], conflict_candidate_id)
        self.assertIn("人工确认接受候选冲突", override_reason)
        self.assertTrue(assignment_confirmed)
        self.assertEqual(scene_status, "assigned")
        self.assertEqual(repeated_ids.count(assignment["candidate_id"]), 1)

    def test_auto_review_uses_score_order_and_skips_duplicate_content(self) -> None:
        project = Project(id="auto-project", name="Auto")
        scene = VisualScene(
            id="auto-scene",
            project_id=project.id,
            scene_index=1,
            start_ms=0,
            end_ms=9_000,
            narration="自动审核测试",
        )
        files = [
            MediaFile(
                id="media-top",
                path=str(self.root / "top.mp4"),
                filename="top.mp4",
                media_type="video",
                file_hash="same-content",
                duration_ms=5_000,
                width=1920,
                height=1080,
            ),
            MediaFile(
                id="media-duplicate",
                path=str(self.root / "duplicate.mp4"),
                filename="duplicate.mp4",
                media_type="video",
                file_hash="same-content",
                duration_ms=5_000,
                width=1920,
                height=1080,
            ),
            MediaFile(
                id="media-next",
                path=str(self.root / "next.mp4"),
                filename="next.mp4",
                media_type="video",
                file_hash="different-content",
                duration_ms=5_000,
                width=1920,
                height=1080,
            ),
        ]
        shots = [
            MediaShot(
                id=f"shot-{index}",
                media_file_id=media.id,
                shot_index=1,
                end_ms=5_000,
            )
            for index, media in enumerate(files, start=1)
        ]
        candidates = [
            SceneCandidate(
                id=f"candidate-{index}",
                project_id=project.id,
                scene_id=scene.id,
                media_shot_id=shot.id,
                total_score=score,
                status="QUALIFIED",
            )
            for index, (shot, score) in enumerate(
                zip(shots, [0.95, 0.90, 0.80]), start=1
            )
        ]

        with Session(self.engine) as session:
            session.add_all([project, scene, *files, *shots, *candidates])
            session.commit()
            result = retrieval_service.auto_assign_qualified_candidates(
                session, project, scene.id
            )
            assignments = session.exec(
                select(SceneAssignment)
                .where(SceneAssignment.scene_id == scene.id)
                .order_by(SceneAssignment.sequence_index)
            ).all()

        self.assertTrue(result["complete"])
        self.assertEqual(
            [item.media_shot_id for item in assignments],
            ["shot-1", "shot-3"],
        )
        self.assertTrue(all(item.manual_confirmed for item in assignments))
        self.assertTrue(
            all("系统按匹配度自动审核通过" in item.selection_reason for item in assignments)
        )

    def test_manual_append_rejects_same_source_content(self) -> None:
        project = Project(id="duplicate-project", name="Duplicate")
        scene = VisualScene(
            id="duplicate-scene",
            project_id=project.id,
            scene_index=1,
            start_ms=0,
            end_ms=10_000,
            narration="重复素材测试",
        )
        media = MediaFile(
            id="duplicate-media",
            path=str(self.root / "duplicate-source.mp4"),
            filename="duplicate-source.mp4",
            media_type="video",
            file_hash="duplicate-hash",
            duration_ms=10_000,
            width=1920,
            height=1080,
        )
        shots = [
            MediaShot(
                id=f"duplicate-shot-{index}",
                media_file_id=media.id,
                shot_index=index,
                start_ms=(index - 1) * 5_000,
                end_ms=index * 5_000,
            )
            for index in (1, 2)
        ]
        candidates = [
            SceneCandidate(
                id=f"duplicate-candidate-{index}",
                project_id=project.id,
                scene_id=scene.id,
                media_shot_id=shot.id,
                total_score=0.9 - index / 10,
                status="QUALIFIED",
            )
            for index, shot in enumerate(shots, start=1)
        ]
        with Session(self.engine) as session:
            session.add_all([project, scene, media, *shots, *candidates])
            session.commit()
            retrieval_service.assign_candidate(
                session,
                project,
                scene.id,
                SceneAssignmentRequest(candidate_id=candidates[0].id, append=True),
            )
            with self.assertRaisesRegex(ValueError, "相同的素材内容"):
                retrieval_service.assign_candidate(
                    session,
                    project,
                    scene.id,
                    SceneAssignmentRequest(candidate_id=candidates[1].id, append=True),
                )

    def test_ingest_asset_generates_review_frames_and_vector_metadata(self) -> None:
        source = self.root / "source.mp4"
        source.write_bytes(b"video")
        media_file = MediaFile(
            id="media-frames",
            path=str(source),
            filename=source.name,
            media_type="video",
            file_hash="frames",
            duration_ms=4_000,
            width=1920,
            height=1080,
        )
        shot = MediaShot(
            id="shot-frames",
            media_file_id=media_file.id,
            shot_index=1,
            start_ms=0,
            end_ms=4_000,
            description="airport traveler",
            tags_json='["airport", "traveler"]',
        )

        def fake_extract(_source, destination, _timestamp, _media_type):
            destination.write_bytes(b"jpeg")

        with Session(self.engine) as session:
            session.add_all([media_file, shot])
            session.commit()
            with (
                patch.object(ingestion_service, "_extract_frame", side_effect=fake_extract),
                patch.object(ingestion_service, "upsert_shot", return_value=17),
                patch.object(
                    ingestion_service,
                    "get_settings",
                    return_value=type("Settings", (), {"workspace_dir": self.root / "workspace"})(),
                ),
            ):
                result = ingestion_service.ingest_asset(session, media_file.id)
                indexed_images = ingestion_service.upsert_shot.call_args.args[2]
            saved_shot = session.get(MediaShot, shot.id)
            frames = session.exec(
                select(MediaKeyframe).where(MediaKeyframe.media_shot_id == shot.id)
            ).all()

        self.assertEqual(result["errors"], [])
        self.assertEqual(len(frames), 3)
        self.assertEqual(saved_shot.vector_id, 17)
        self.assertTrue(saved_shot.thumbnail_path)
        self.assertEqual(
            result["asset"]["shots"][0]["vector_model"],
            "Qwen/Qwen3-VL-Embedding-2B",
        )
        self.assertEqual(len(indexed_images), 3)

    def test_delete_assets_removes_records_and_previews_but_preserves_sources(self) -> None:
        source = self.root / "source.mp4"
        source.write_bytes(b"original-video")
        workspace = self.root / "workspace"
        preview_dir = workspace / "assets" / "media-delete" / "shot-delete"
        preview_dir.mkdir(parents=True)
        preview = preview_dir / "frame_01.jpg"
        preview.write_bytes(b"preview")
        media_file = MediaFile(
            id="media-delete",
            path=str(source),
            filename=source.name,
            media_type="video",
            file_hash="delete-hash",
        )
        shot = MediaShot(
            id="shot-delete",
            media_file_id=media_file.id,
            shot_index=1,
            thumbnail_path=str(preview),
            vector_id=7,
        )
        keyframe = MediaKeyframe(
            id="frame-delete",
            media_shot_id=shot.id,
            frame_index=1,
            timestamp_ms=0,
            path=str(preview),
        )
        project = Project(id="delete-project", name="Delete")
        scene = VisualScene(
            id="delete-scene",
            project_id=project.id,
            scene_index=1,
            start_ms=0,
            end_ms=1000,
            narration="Delete assigned media.",
            status="assigned",
        )
        candidate = SceneCandidate(
            id="delete-candidate",
            project_id=project.id,
            scene_id=scene.id,
            media_shot_id=shot.id,
        )
        assignment = SceneAssignment(
            id="delete-assignment",
            project_id=project.id,
            scene_id=scene.id,
            media_shot_id=shot.id,
            candidate_id=candidate.id,
        )
        media_id = media_file.id
        shot_id = shot.id
        keyframe_id = keyframe.id
        candidate_id = candidate.id
        assignment_id = assignment.id
        scene_id = scene.id

        with Session(self.engine) as session:
            session.add_all([media_file, shot, keyframe, project, scene, candidate, assignment])
            session.commit()
            with (
                patch.object(ingestion_service, "remove_shot") as remove_vector,
                patch.object(
                    ingestion_service,
                    "get_settings",
                    return_value=type("Settings", (), {"workspace_dir": workspace})(),
                ),
            ):
                result = ingestion_service.delete_assets(session, [media_id, "missing"])

            self.assertIsNone(session.get(MediaFile, media_id))
            self.assertIsNone(session.get(MediaShot, shot_id))
            self.assertIsNone(session.get(MediaKeyframe, keyframe_id))
            self.assertIsNone(session.get(SceneCandidate, candidate_id))
            self.assertIsNone(session.get(SceneAssignment, assignment_id))
            self.assertEqual(session.get(VisualScene, scene_id).status, "generated")

        self.assertEqual(result["deleted_ids"], [media_id])
        self.assertEqual(result["missing_ids"], ["missing"])
        self.assertEqual(result["deleted_preview_files"], 1)
        self.assertEqual(result["source_files_preserved"], 1)
        self.assertTrue(source.is_file())
        self.assertFalse(preview.exists())
        remove_vector.assert_called_once_with(shot_id)

    def test_landscape_assets_only_appear_as_an_allowed_final_fallback(self) -> None:
        storyboard = StoryboardContent(
            visual_summary="A reflective transition",
            visual_type="transition",
            scene_category="transition",
            mood="reflective",
            shot_preference="wide",
            primary_query="reflective transition",
            fallback_category="transition",
            fallback_mood="reflective",
            allow_landscape_fallback=True,
            confidence=0.8,
        )
        project = Project(id="fallback-project", name="Fallback")
        scene = VisualScene(
            id="fallback-scene",
            project_id=project.id,
            scene_index=1,
            start_ms=0,
            end_ms=5000,
            narration="Time passed.",
            storyboard_json=storyboard.model_dump_json(),
        )
        media_file = MediaFile(
            id="landscape-file",
            path=str(self.root / "mountain.mp4"),
            filename="mountain.mp4",
            media_type="video",
            file_hash="landscape-hash",
            duration_ms=5000,
            width=1920,
            height=1080,
            library_role="landscape_fallback",
            fallback_category="landscape",
            mood="reflective",
        )
        shot = MediaShot(
            id="landscape-shot",
            media_file_id=media_file.id,
            shot_index=1,
            start_ms=0,
            end_ms=5000,
            description="quiet mountain sunset",
            tags_json='["mountain", "sunset", "reflective"]',
            library_role="landscape_fallback",
            fallback_category="landscape",
            mood="reflective",
        )

        with Session(self.engine) as session:
            session.add_all([project, scene, media_file, shot])
            session.commit()
            with patch.object(retrieval_service.media_provider_service, "PROVIDER_ORDER", []):
                allowed = retrieval_service.search_scene_candidates(session, project, scene.id)
            self.assertEqual(allowed["status"], "FALLBACK_REQUIRED")
            self.assertEqual(allowed["candidates"][0]["selection_stage"], "landscape_fallback")
            self.assertTrue(allowed["candidates"][0]["is_fallback"])

            storyboard.allow_landscape_fallback = False
            scene.storyboard_json = storyboard.model_dump_json()
            session.add(scene)
            session.commit()
            with patch.object(retrieval_service.media_provider_service, "PROVIDER_ORDER", []):
                blocked = retrieval_service.search_scene_candidates(session, project, scene.id)
            self.assertEqual(blocked["status"], "NO_RESULT")
            self.assertEqual(blocked["candidates"], [])

    def test_themed_fallback_auto_fills_track_and_waits_for_review(self) -> None:
        project = Project(id="auto-fallback-project", name="Auto fallback")
        scene = VisualScene(
            id="auto-fallback-scene",
            project_id=project.id,
            scene_index=1,
            start_ms=0,
            end_ms=10_000,
            narration="Business transition",
        )
        records = [project, scene]
        for index in (1, 2):
            media = MediaFile(
                id=f"fallback-media-{index}",
                path=str(self.root / f"business-{index}.mp4"),
                filename=f"business-{index}.mp4",
                media_type="video",
                file_hash=f"fallback-hash-{index}",
                duration_ms=5_000,
                width=1920,
                height=1080,
                library_role="themed_fallback",
                fallback_category="business",
            )
            shot = MediaShot(
                id=f"fallback-shot-{index}",
                media_file_id=media.id,
                shot_index=1,
                start_ms=0,
                end_ms=5_000,
                library_role="themed_fallback",
                fallback_category="business",
            )
            candidate = SceneCandidate(
                id=f"fallback-candidate-{index}",
                project_id=project.id,
                scene_id=scene.id,
                media_shot_id=shot.id,
                total_score=0.8 - index * 0.1,
                status="QUALIFIED",
                selection_stage="themed_fallback",
                is_fallback=True,
            )
            records.extend([media, shot, candidate])

        settings = type(
            "Settings",
            (),
            {
                "auto_fallback_enabled": True,
                "auto_landscape_fallback_enabled": False,
                "auto_fallback_review_required": True,
                "auto_fallback_max_ratio_percent": 100,
                "auto_fallback_max_consecutive_shots": 2,
            },
        )()
        with Session(self.engine) as session:
            session.add_all(records)
            session.commit()
            candidates = retrieval_service.list_scene_candidates(session, project.id, scene.id)
            with patch.object(fallback_service, "get_settings", return_value=settings):
                result = fallback_service.auto_fill_scene(
                    session, project, scene, candidates
                )

            assignments = retrieval_service.list_scene_assignments(
                session, project.id, scene.id
            )
            self.assertTrue(result["complete"])
            self.assertEqual(len(result["selected_assignment_ids"]), 2)
            self.assertTrue(assignments["coverage"]["review_required"])
            self.assertTrue(all(not item["manual_confirmed"] for item in assignments["assignments"]))

            confirmed = retrieval_service.confirm_scene_fallback_assignments(
                session, project.id, scene.id
            )
            self.assertFalse(confirmed["coverage"]["review_required"])


if __name__ == "__main__":
    unittest.main()
