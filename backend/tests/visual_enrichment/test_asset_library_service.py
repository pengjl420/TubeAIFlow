import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine, select

from app.models.media import MediaFile, MediaShot, SceneAssignment, SceneCandidate
from app.models.project import Project
from app.models.storyboard import VisualScene
from app.services.visual_enrichment import asset_library_service
from app.services.storyboard import scene_workspace_service
from app.services.rendering import scene_renderer


def _storyboard() -> str:
    return json.dumps(
        {
            "visual_summary": "A misty forest at sunrise",
            "visual_type": "b_roll",
            "entities": [],
            "locations": ["forest"],
            "time_period": "",
            "scene_category": "nature",
            "mood": "calm",
            "shot_preference": "wide",
            "primary_query": "misty forest sunrise",
            "alternative_queries": ["calm woods"],
            "fallback_category": "landscape",
            "fallback_mood": "calm",
            "confidence": 0.9,
        }
    )


def test_scan_rank_and_assign_local_asset(tmp_path):
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    clip = media_dir / "misty-forest-sunrise.mp4"
    clip.write_bytes(b"video-content")
    project = Project(
        id="project",
        name="Project",
        output_dir=str(tmp_path),
        config_json=json.dumps({"media_video_dir": str(media_dir)}),
    )
    scene = VisualScene(
        id="scene",
        project_id=project.id,
        scene_index=1,
        start_ms=0,
        end_ms=5_000,
        narration="A calm forest",
        storyboard_json=_storyboard(),
    )
    with Session(engine) as session:
        session.add(project)
        session.add(scene)
        session.commit()
        with patch.object(
            asset_library_service,
            "probe_media",
            return_value={"duration_ms": 10_000, "width": 1920, "height": 1080},
        ):
            scanned = asset_library_service.scan_project_directory(session, project)
        candidates = asset_library_service.scene_candidates(session, project, scene.id)
        cached_candidates = asset_library_service.scene_candidates(session, project, scene.id)
        assert [item["id"] for item in cached_candidates] == [
            item["id"] for item in candidates
        ]
        with patch.object(
            scene_workspace_service,
            "get_settings",
            return_value=SimpleNamespace(workspace_dir=tmp_path / "workspace"),
        ):
            result = asset_library_service.assign_local_candidate(
                session, project, scene.id, candidates[0]["id"]
            )

        assert scanned["indexed"] == 1
        assert candidates[0]["filename"] == clip.name
        assert candidates[0]["score"] > 0.5
        assert result["coverage"]["complete"] is True
        assert session.exec(select(MediaFile)).one().provider == "local_library"
        assert session.exec(select(SceneCandidate)).one().status == "RECOMMENDED"
        assignment = session.exec(select(SceneAssignment)).one()
        assert assignment.selection_stage == "manual_local_asset"
        shot = session.get(MediaShot, assignment.media_shot_id)
        media = session.get(MediaFile, shot.media_file_id)
        scene_renderer.validate_visual_assignment(assignment, shot, media)
    engine.dispose()


def test_scan_deduplicates_identical_content(tmp_path):
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    (media_dir / "one.mp4").write_bytes(b"same")
    (media_dir / "two.mp4").write_bytes(b"same")
    project = Project(
        id="project",
        name="Project",
        config_json=json.dumps({"media_video_dir": str(media_dir)}),
    )
    with Session(engine) as session:
        with patch.object(
            asset_library_service,
            "probe_media",
            return_value={"duration_ms": 1_000, "width": 1280, "height": 720},
        ):
            result = asset_library_service.scan_project_directory(session, project)
        assert result["indexed"] == 1
        assert result["skipped"] == 1
    engine.dispose()


def test_identical_content_in_different_library_roots_remains_addressable(tmp_path):
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    (first_root / "clip.mp4").write_bytes(b"same")
    (second_root / "clip.mp4").write_bytes(b"same")
    first = Project(
        id="first", name="First", config_json=json.dumps({"media_video_dir": str(first_root)})
    )
    second = Project(
        id="second", name="Second", config_json=json.dumps({"media_video_dir": str(second_root)})
    )
    with Session(engine) as session:
        with patch.object(
            asset_library_service,
            "probe_media",
            return_value={"duration_ms": 1_000, "width": 1280, "height": 720},
        ):
            assert asset_library_service.scan_project_directory(session, first)["indexed"] == 1
            assert asset_library_service.scan_project_directory(session, second)["indexed"] == 1
        paths = {Path(item.path).parent for item in session.exec(select(MediaFile)).all()}
        assert paths == {first_root, second_root}
    engine.dispose()


def test_unchanged_library_file_skips_hash_and_probe_on_rescan(tmp_path):
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    (media_dir / "clip.mp4").write_bytes(b"video")
    project = Project(
        id="project", name="Project", config_json=json.dumps({"media_video_dir": str(media_dir)})
    )
    with Session(engine) as session:
        with (
            patch.object(
                asset_library_service,
                "probe_media",
                return_value={"duration_ms": 1_000, "width": 1280, "height": 720},
            ) as probe,
            patch.object(
                asset_library_service, "_sha256", return_value="a" * 64
            ) as digest,
        ):
            asset_library_service.scan_project_directory(session, project)
            asset_library_service.scan_project_directory(session, project)
        assert probe.call_count == 1
        assert digest.call_count == 1
    engine.dispose()
