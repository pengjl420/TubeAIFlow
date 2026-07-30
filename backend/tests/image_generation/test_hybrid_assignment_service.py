import json

from sqlmodel import Session, SQLModel, create_engine, select

from app.models.media import MediaFile, MediaShot, SceneAssignment
from app.models.project import Project
from app.models.storyboard import VisualScene
from app.services.image_generation import hybrid_assignment_service


def _storyboard(allow_landscape: bool) -> str:
    return json.dumps(
        {
            "visual_summary": "A calm transition landscape",
            "visual_type": "documentary",
            "entities": [],
            "locations": [],
            "time_period": "",
            "scene_category": "transition",
            "mood": "reflective",
            "shot_preference": "wide",
            "primary_query": "calm landscape",
            "alternative_queries": [],
            "fallback_category": "landscape",
            "fallback_mood": "reflective",
            "allow_landscape_fallback": allow_landscape,
            "must_include": [],
            "avoid": [],
            "confidence": 0.9,
        }
    )


def test_mixed_assignment_keeps_ai_scenes_and_uses_local_video(tmp_path, monkeypatch):
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    material_dir = tmp_path / "landscape"
    material_dir.mkdir()
    clips = [material_dir / "lake.mp4", material_dir / "mountain.mp4"]
    for index, clip in enumerate(clips):
        clip.write_bytes(f"local-video-{index}".encode())

    monkeypatch.setattr(
        hybrid_assignment_service,
        "probe_media",
        lambda _path: {"duration_ms": 12_000, "width": 1920, "height": 1080},
    )
    project = Project(
        id="mixed-project",
        name="Mixed",
        output_dir=str(tmp_path),
        config_json=json.dumps(
            {
                "video_mode": "ai_landscape_mix",
                "media_video_dir": str(material_dir),
                "landscape_mix_ratio": 0.5,
            }
        ),
    )
    scenes = [
        VisualScene(
            id=f"scene-{index}",
            project_id=project.id,
            scene_index=index,
            start_ms=(index - 1) * 8_000,
            end_ms=index * 8_000,
            narration=f"Scene {index}",
            storyboard_json=_storyboard(index in {2, 4}),
        )
        for index in range(1, 5)
    ]

    with Session(engine) as session:
        session.add(project)
        session.add_all(scenes)
        session.commit()

        result = hybrid_assignment_service.assign_landscape_scenes(session, project)
        assignments = list(session.exec(select(SceneAssignment)).all())

        assert result["landscape_scene_count"] == 2
        assert {item.scene_id for item in assignments} == {"scene-2", "scene-4"}
        assert all(item.selection_stage == "local_landscape_mix" for item in assignments)
        assert all(item.scene_offset_end_ms == 8_000 for item in assignments)
        assert len({scene.id for scene in scenes} - {item.scene_id for item in assignments}) == 2


def test_mixed_assignment_skips_duplicate_content_within_project(tmp_path, monkeypatch):
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    material_dir = tmp_path / "landscape"
    material_dir.mkdir()
    clips = [
        material_dir / "duplicate-a.mp4",
        material_dir / "duplicate-b.mp4",
        material_dir / "unique.mp4",
    ]
    clips[0].write_bytes(b"duplicate-video")
    clips[1].write_bytes(b"duplicate-video")
    clips[2].write_bytes(b"unique-video")

    monkeypatch.setattr(
        hybrid_assignment_service,
        "probe_media",
        lambda _path: {"duration_ms": 12_000, "width": 1920, "height": 1080},
    )
    monkeypatch.setattr(
        hybrid_assignment_service,
        "_randomize_for_project",
        lambda paths, _project_id: paths,
    )
    project = Project(
        id="deduplicated-project",
        name="Deduplicated",
        output_dir=str(tmp_path),
        config_json=json.dumps(
            {
                "video_mode": "ai_landscape_mix",
                "media_video_dir": str(material_dir),
                "landscape_mix_ratio": 0.5,
            }
        ),
    )
    scenes = [
        VisualScene(
            id=f"deduplicated-scene-{index}",
            project_id=project.id,
            scene_index=index,
            start_ms=(index - 1) * 8_000,
            end_ms=index * 8_000,
            narration=f"Scene {index}",
            storyboard_json=_storyboard(True),
        )
        for index in range(1, 5)
    ]

    with Session(engine) as session:
        session.add(project)
        session.add_all(scenes)
        session.commit()

        result = hybrid_assignment_service.assign_landscape_scenes(session, project)
        assignments = list(
            session.exec(
                select(SceneAssignment).where(SceneAssignment.project_id == project.id)
            ).all()
        )
        media_files = list(session.exec(select(MediaFile)).all())

        assert result["landscape_scene_count"] == 2
        assert len(assignments) == 2
        assert len({item.media_shot_id for item in assignments}) == 2
        assert len(media_files) == 2


def test_mixed_assignment_allows_same_material_in_different_projects(tmp_path, monkeypatch):
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    material_dir = tmp_path / "landscape"
    material_dir.mkdir()
    (material_dir / "shared.mp4").write_bytes(b"shared-video")
    (material_dir / "other.mp4").write_bytes(b"other-video")

    monkeypatch.setattr(
        hybrid_assignment_service,
        "probe_media",
        lambda _path: {"duration_ms": 12_000, "width": 1920, "height": 1080},
    )
    monkeypatch.setattr(
        hybrid_assignment_service,
        "_randomize_for_project",
        lambda paths, _project_id: paths,
    )
    projects = [
        Project(
            id=f"shared-project-{index}",
            name=f"Shared {index}",
            output_dir=str(tmp_path),
            config_json=json.dumps(
                {
                    "video_mode": "ai_landscape_mix",
                    "media_video_dir": str(material_dir),
                    "landscape_mix_ratio": 0.5,
                }
            ),
        )
        for index in range(1, 3)
    ]
    scenes = [
        VisualScene(
            id=f"{project.id}-scene-{index}",
            project_id=project.id,
            scene_index=index,
            start_ms=(index - 1) * 8_000,
            end_ms=index * 8_000,
            narration=f"Scene {index}",
            storyboard_json=_storyboard(index == 1),
        )
        for project in projects
        for index in range(1, 3)
    ]

    with Session(engine) as session:
        session.add_all(projects)
        session.add_all(scenes)
        session.commit()

        for project in projects:
            hybrid_assignment_service.assign_landscape_scenes(session, project)

        assignments = list(session.exec(select(SceneAssignment)).all())
        shots = {item.id: item for item in session.exec(select(MediaShot)).all()}

        assert len(assignments) == 2
        assert assignments[0].project_id != assignments[1].project_id
        assert (
            shots[assignments[0].media_shot_id].media_file_id
            == shots[assignments[1].media_shot_id].media_file_id
        )


def test_mixed_assignment_does_not_use_disallowed_concrete_scenes(tmp_path):
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    material_dir = tmp_path / "landscape"
    material_dir.mkdir()
    project = Project(
        id="concrete-project",
        name="Concrete",
        output_dir=str(tmp_path),
        config_json=json.dumps(
            {"video_mode": "ai_landscape_mix", "media_video_dir": str(material_dir)}
        ),
    )
    scenes = [
        VisualScene(
            id=f"scene-{index}",
            project_id=project.id,
            scene_index=index,
            start_ms=(index - 1) * 5_000,
            end_ms=index * 5_000,
            narration=f"Scene {index}",
            storyboard_json=_storyboard(False),
        )
        for index in range(1, 3)
    ]

    with Session(engine) as session:
        session.add(project)
        session.add_all(scenes)
        session.commit()

        result = hybrid_assignment_service.assign_landscape_scenes(session, project)

        assert result["landscape_scene_count"] == 0
        assert list(session.exec(select(SceneAssignment)).all()) == []
