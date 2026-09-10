import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models.media import MediaFile, MediaShot, SceneAssignment
from app.models.narration import Segment
from app.models.project import Project
from app.models.storyboard import SubtitleCue, VisualScene
from app.services.rendering import timeline_editor_service


class TimelineEditorServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temp_dir.cleanup()

    def _seed(self, session: Session) -> tuple[Project, SceneAssignment, SceneAssignment]:
        project = Project(
            id="project-1",
            name="Timeline",
            config_json='{"fps": 25}',
        )
        scene = VisualScene(
            id="scene-1",
            project_id=project.id,
            scene_index=1,
            start_ms=1_000,
            end_ms=7_000,
            narration="Narration",
        )
        media = MediaFile(
            id="media-1",
            path="asset.png",
            filename="asset.png",
            media_type="image",
            file_hash="hash-1",
        )
        shot = MediaShot(
            id="shot-1",
            media_file_id=media.id,
            shot_index=1,
            start_ms=0,
        )
        first = SceneAssignment(
            id="clip-1",
            project_id=project.id,
            scene_id=scene.id,
            media_shot_id=shot.id,
            sequence_index=1,
            scene_offset_start_ms=0,
            scene_offset_end_ms=3_000,
            display_duration_ms=3_000,
        )
        second = SceneAssignment(
            id="clip-2",
            project_id=project.id,
            scene_id=scene.id,
            media_shot_id=shot.id,
            sequence_index=2,
            scene_offset_start_ms=3_000,
            scene_offset_end_ms=6_000,
            display_duration_ms=3_000,
        )
        session.add_all(
            [
                project,
                scene,
                media,
                shot,
                first,
                second,
                Segment(
                    id="segment-1",
                    segment_id="segment-1",
                    project_id=project.id,
                    segment_index=1,
                    text="Narration",
                    audio_path="audio.wav",
                    start_time=0,
                    end_time=8,
                    duration=8,
                ),
                SubtitleCue(
                    id="cue-1",
                    project_id=project.id,
                    source_segment_id="segment-1",
                    cue_index=1,
                    start_ms=0,
                    end_ms=2_000,
                    text="Caption",
                ),
            ]
        )
        session.commit()
        return project, first, second

    def test_timeline_exposes_visual_audio_and_subtitle_tracks(self) -> None:
        with Session(self.engine) as session:
            project, _, _ = self._seed(session)

            result = timeline_editor_service.timeline(session, project)

        self.assertEqual(result["format_version"], 1)
        self.assertEqual(result["fps"], 25)
        self.assertEqual(result["duration_ms"], 8_000)
        self.assertEqual(
            [track["type"] for track in result["tracks"]], ["video", "audio", "subtitle"]
        )
        self.assertEqual(result["tracks"][0]["clips"][0]["start_ms"], 1_000)
        self.assertEqual(result["tracks"][0]["clips"][1]["end_ms"], 7_000)

    def test_update_reorders_and_reflows_scene_clips(self) -> None:
        with Session(self.engine) as session:
            project, first, second = self._seed(session)
            settings = SimpleNamespace(workspace_dir=Path(self.temp_dir.name))
            with (
                patch.object(timeline_editor_service, "invalidate_scene_outputs"),
                patch.object(timeline_editor_service, "get_settings", return_value=settings),
            ):
                result = timeline_editor_service.update_visual_clip(
                    session,
                    project,
                    second.id,
                    {"sequence_index": 1, "display_duration_ms": 2_000, "motion_type": "static"},
                )

            first = session.get(SceneAssignment, first.id)
            second = session.get(SceneAssignment, second.id)

        self.assertEqual(second.sequence_index, 1)
        self.assertEqual(second.scene_offset_start_ms, 0)
        self.assertEqual(second.scene_offset_end_ms, 2_000)
        self.assertEqual(second.motion_type, "static")
        self.assertEqual(first.sequence_index, 2)
        self.assertEqual(first.scene_offset_start_ms, 2_000)
        self.assertEqual(result["tracks"][0]["clips"][0]["id"], second.id)
        saved = Path(self.temp_dir.name) / "projects" / project.id / "timeline" / "timeline.json"
        self.assertEqual(json.loads(saved.read_text(encoding="utf-8"))["format_version"], 1)

    def test_locked_visual_rejects_timeline_edits(self) -> None:
        with Session(self.engine) as session:
            project, first, _ = self._seed(session)
            scene = session.get(VisualScene, first.scene_id)
            scene.locked_visual = True
            session.add(scene)
            session.commit()

            with self.assertRaisesRegex(ValueError, "visual is locked"):
                timeline_editor_service.update_visual_clip(
                    session, project, first.id, {"display_duration_ms": 2_000}
                )


if __name__ == "__main__":
    unittest.main()
