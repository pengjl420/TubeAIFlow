import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from xml.etree import ElementTree as ET

from sqlmodel import Session, SQLModel, create_engine

from app.models.media import MediaFile, MediaShot, SceneAssignment
from app.models.project import Project
from app.models.storyboard import SubtitleCue, VisualScene
from app.services.projects import fcpxml_export_service, prproj_export_service, project_service
from app.services.rendering import rough_cut_service


class FcpxmlExportTests(unittest.TestCase):
    def test_export_writes_editable_timeline_with_media_audio_and_subtitles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_dir = root / "output"
            output_dir.mkdir()
            source_path = root / "source.mp4"
            source_path.write_bytes(b"video")
            audio_path = output_dir / "Story.wav"
            audio_path.write_bytes(b"audio")

            engine = create_engine(f"sqlite:///{root / 'test.db'}")
            SQLModel.metadata.create_all(engine)
            with Session(engine) as session:
                project = Project(
                    id="project-id",
                    name="Story",
                    output_dir=str(output_dir),
                    config_json='{"output_filename":"Story","project_directory_name":"Story","video_mode":"ai_generated_images","video_output_format":"fcpxml"}',
                )
                scene = VisualScene(
                    id="scene-1", project_id=project.id, scene_index=1,
                    start_ms=0, end_ms=2_000, narration="Narration",
                )
                media = MediaFile(
                    id="media-1", path=str(source_path), filename=source_path.name,
                    media_type="video", file_hash="hash", duration_ms=10_000,
                    width=1920, height=1080,
                )
                shot = MediaShot(
                    id="shot-1", media_file_id=media.id, shot_index=1,
                    start_ms=1_000, end_ms=5_000,
                )
                assignment = SceneAssignment(
                    id="assignment-1", project_id=project.id, scene_id=scene.id,
                    media_shot_id=shot.id, scene_offset_start_ms=0,
                    scene_offset_end_ms=2_000, trim_start_ms=500,
                    trim_end_ms=2_500, manual_confirmed=True,
                )
                cue = SubtitleCue(
                    id="cue-1", project_id=project.id, source_segment_id="segment-1",
                    cue_index=1, start_ms=100, end_ms=1_900, text="Hello & goodbye",
                )
                session.add(project)
                session.add(scene)
                session.add(media)
                session.add(shot)
                session.add(assignment)
                session.add(cue)
                session.commit()

                with patch.object(
                    fcpxml_export_service,
                    "get_settings",
                    return_value=SimpleNamespace(workspace_dir=root / "workspace"),
                ):
                    report = fcpxml_export_service.export_project_fcpxml(session, project)

            output_path = Path(report["path"])
            self.assertEqual(output_path, output_dir / "Story.fcpxml")
            self.assertTrue(output_path.is_file())
            document = ET.parse(output_path).getroot()
            self.assertEqual(document.tag, "fcpxml")
            self.assertEqual(document.attrib["version"], "1.10")
            clips = document.findall("./library/event/project/sequence/spine/asset-clip")
            self.assertEqual(len(clips), 1)
            self.assertEqual(clips[0].attrib["start"], "3/2s")
            self.assertEqual(clips[0].attrib["duration"], "2/1s")
            self.assertEqual(document.findtext(".//title/text/text-style"), "Hello & goodbye")
            resource_uris = [item.attrib["src"] for item in document.findall(".//media-rep")]
            self.assertIn(source_path.resolve().as_uri(), resource_uris)
            self.assertIn(audio_path.resolve().as_uri(), resource_uris)
            engine.dispose()

    def test_unknown_output_format_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported video output format"):
            project_service.normalize_video_output_format("mov")

    def test_prproj_and_dual_output_formats_are_supported(self) -> None:
        self.assertEqual(project_service.normalize_video_output_format("prproj"), "prproj")
        self.assertEqual(project_service.normalize_video_output_format("editable_both"), "editable_both")

    def test_prproj_export_uses_premiere_conversion_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_dir = root / "output"
            output_dir.mkdir()
            fcpxml_path = output_dir / "Story.fcpxml"
            fcpxml_path.write_text("<fcpxml version=\"1.10\"/>", encoding="utf-8")
            executable = root / "Adobe Premiere Pro.exe"
            executable.write_bytes(b"exe")
            settings = SimpleNamespace(workspace_dir=root / "workspace")
            project = Project(
                id="prproj-project", name="Story", output_dir=str(output_dir),
                config_json='{"output_filename":"Story","project_directory_name":"Story","video_mode":"none"}',
            )
            engine = create_engine(f"sqlite:///{root / 'prproj.db'}")
            SQLModel.metadata.create_all(engine)
            with Session(engine) as session:
                session.add(project)
                session.commit()

                def create_output(_executable, _script, marker, output, _timeout):
                    output.write_bytes(b"native-prproj")
                    marker.write_text('{"success":true}', encoding="utf-8")

                with (
                    patch.object(prproj_export_service, "get_settings", return_value=settings),
                    patch.object(
                        prproj_export_service.fcpxml_export_service,
                        "export_project_fcpxml",
                        return_value={"path": str(fcpxml_path), "format": "fcpxml"},
                    ),
                    patch.object(prproj_export_service, "_run_premiere_conversion", side_effect=create_output),
                ):
                    report = prproj_export_service.export_project_prproj(
                        session, project, premiere_executable=executable
                    )

            self.assertEqual(Path(report["path"]), output_dir / "Story.prproj")
            self.assertEqual((output_dir / "Story.prproj").read_bytes(), b"native-prproj")
            self.assertEqual(report["format"], "prproj")
            self.assertEqual(report["source_fcpxml_path"], str(fcpxml_path.resolve()))
            engine.dispose()

    def test_landscape_mode_exports_selected_sources_without_rendering_mp4(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_dir = root / "output"
            media_dir = root / "media"
            output_dir.mkdir()
            media_dir.mkdir()
            source_path = media_dir / "landscape.mp4"
            source_path.write_bytes(b"video")
            audio_path = output_dir / "Story.wav"
            audio_path.write_bytes(b"audio")
            settings = SimpleNamespace(
                workspace_dir=root / "workspace",
                storyboard_transition_effects=[],
                storyboard_transition_group_min_clips=2,
                storyboard_transition_group_max_clips=5,
                storyboard_transition_min_per_group=1,
                storyboard_transition_max_per_group=2,
                storyboard_transition_duration_seconds=0.45,
            )

            engine = create_engine(f"sqlite:///{root / 'landscape.db'}")
            SQLModel.metadata.create_all(engine)
            with Session(engine) as session:
                project = Project(
                    id="landscape-project",
                    name="Story",
                    output_dir=str(output_dir),
                    config_json=(
                        '{"output_filename":"Story","project_directory_name":"Story",'
                        f'"media_video_dir":{json.dumps(str(media_dir))},'
                        '"video_mode":"landscape","video_output_format":"fcpxml"}'
                    ),
                )
                session.add(project)
                session.commit()
                with (
                    patch.object(fcpxml_export_service, "get_settings", return_value=settings),
                    patch.object(rough_cut_service, "get_settings", return_value=settings),
                    patch.object(rough_cut_service, "probe_duration", side_effect=lambda path: 4.0 if Path(path) == audio_path else 8.0),
                ):
                    report = fcpxml_export_service.export_project_fcpxml(session, project)

            document = ET.parse(report["path"]).getroot()
            clips = document.findall("./library/event/project/sequence/spine/asset-clip")
            self.assertEqual(len(clips), 1)
            self.assertEqual(clips[0].attrib["duration"], "4/1s")
            self.assertIn(source_path.resolve().as_uri(), [item.attrib["src"] for item in document.findall(".//media-rep")])
            self.assertFalse((output_dir / "Story.mp4").exists())
            engine.dispose()

    def test_audio_only_mode_exports_narration_and_subtitle_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_dir = root / "output"
            output_dir.mkdir()
            audio_path = output_dir / "Story.wav"
            audio_path.write_bytes(b"audio")
            settings = SimpleNamespace(workspace_dir=root / "workspace")
            engine = create_engine(f"sqlite:///{root / 'audio-only.db'}")
            SQLModel.metadata.create_all(engine)
            with Session(engine) as session:
                project = Project(
                    id="audio-project",
                    name="Story",
                    output_dir=str(output_dir),
                    config_json='{"output_filename":"Story","project_directory_name":"Story","video_mode":"none","video_output_format":"fcpxml"}',
                )
                session.add(project)
                session.add(
                    SubtitleCue(
                        id="cue-1", project_id=project.id, source_segment_id="segment-1",
                        cue_index=1, start_ms=0, end_ms=2_000, text="Audio only subtitle",
                    )
                )
                session.commit()
                with (
                    patch.object(fcpxml_export_service, "get_settings", return_value=settings),
                    patch.object(fcpxml_export_service, "probe_duration", return_value=2.0),
                ):
                    report = fcpxml_export_service.export_project_fcpxml(session, project)

            document = ET.parse(report["path"]).getroot()
            self.assertIsNotNone(document.find("./library/event/project/sequence/spine/gap"))
            self.assertEqual(document.findtext(".//title/text/text-style"), "Audio only subtitle")
            self.assertEqual(len(document.findall(".//media-rep")), 1)
            self.assertEqual(report["clip_count"], 0)
            engine.dispose()
if __name__ == "__main__":
    unittest.main()
