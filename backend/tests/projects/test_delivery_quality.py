import tempfile
import unittest
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

from app.models.media import MediaFile, MediaShot, SceneAssignment
from app.models.project import Project
from app.models.storyboard import SubtitleCue, VisualScene
from app.services.quality import qa_service


class DeliveryQualityTests(unittest.TestCase):
    def test_checks_editable_delivery_without_requiring_rendered_video(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            source = root / "source.png"
            source.write_bytes(b"image")
            for name in ("Story.wav", "Story.srt", "Story.prproj"):
                (output / name).write_bytes(b"delivery")
            (output / "Story.srt").write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n"
                "2\n00:00:01,000 --> 00:00:02,000\nA long second subtitle line\n",
                encoding="utf-8")

            engine = create_engine("sqlite://")
            SQLModel.metadata.create_all(engine)
            with Session(engine) as session:
                project = Project(id="project", name="Story", output_dir=str(output))
                scene = VisualScene(id="scene", project_id=project.id, scene_index=1,
                                    start_ms=0, end_ms=2000, narration="Hello")
                media = MediaFile(id="media", path=str(source), filename=source.name,
                                  media_type="image", file_hash="hash")
                shot = MediaShot(id="shot", media_file_id=media.id, shot_index=1)
                assignment = SceneAssignment(id="assignment", project_id=project.id,
                                             scene_id=scene.id, media_shot_id=shot.id,
                                             scene_offset_start_ms=0, scene_offset_end_ms=2000,
                                             display_duration_ms=2000)
                cue = SubtitleCue(id="cue", project_id=project.id, source_segment_id="segment",
                                  cue_index=1, start_ms=0, end_ms=1000, text="Hello")
                second_cue = SubtitleCue(id="cue-2", project_id=project.id,
                                         source_segment_id="segment-2", cue_index=1,
                                         start_ms=1000, end_ms=2000,
                                         text="A long second subtitle line")
                session.add_all([project, scene, media, shot, assignment, cue, second_cue])
                session.commit()
                settings = SimpleNamespace(workspace_dir=root / "workspace")
                with patch.object(qa_service, "get_settings", return_value=settings), \
                     patch.object(qa_service, "probe_duration", return_value=2.0), \
                     patch.object(qa_service, "analyze_audio_quality", return_value={}):
                    report = qa_service.run_quality_check(session, project)
                    self.assertFalse(report["passed"])
                    self.assertFalse(report["premiere_conversion_verified"])
                    self.assertEqual(report["summary"]["error_count"], 1)
                    self.assertNotIn("video_missing", {item["type"] for item in report["issues"]})
                    self.assertIn("prproj_conversion_unverified",
                                  {item["type"] for item in report["issues"]})
                    second_issue = next(item for item in report["issues"]
                                        if item["subtitle_id"] == second_cue.id)
                    self.assertEqual(second_issue["subtitle_cue_index"], 2)
                    self.assertEqual(qa_service.read_report(project), report)
                    self.assertEqual(assignment.scene_offset_end_ms, 2000)

                    conversion_path = output / "Story" / "reports" / "prproj_export_report.json"
                    conversion_path.parent.mkdir(parents=True, exist_ok=True)
                    source_fcpxml = output / "Story.fcpxml"
                    source_premiere_xml = output / "Story.xml"
                    source_fcpxml.write_bytes(b"fcpxml")
                    source_premiere_xml.write_bytes(b"premiere-xml")
                    conversion_path.write_text(json.dumps({
                                                           "export_id": "export-1",
                                                           "created_at": "2026-09-22T00:00:00+00:00",
                                                           "format": "prproj",
                                                           "path": str(output / "Story.prproj"),
                                                           "premiere_executable": "Premiere.exe",
                                                           "premiere_result": {"success": True},
                                                           "source_fcpxml_path": str(source_fcpxml),
                                                           "source_premiere_xml_path": str(
                                                               source_premiere_xml
                                                           ),
                                                           "source_fcpxml_signature": qa_service._file_signature(
                                                               source_fcpxml, strong=True
                                                           ),
                                                           "source_premiere_xml_signature": qa_service._file_signature(
                                                               source_premiere_xml, strong=True
                                                           ),
                                                           "prproj_signature": qa_service._file_signature(
                                                               output / "Story.prproj",
                                                               strong=True,
                                                           ),
                                                           }),
                                               encoding="utf-8")
                    report = qa_service.run_quality_check(session, project)
                    self.assertNotIn("prproj_conversion_unverified",
                                     {item["type"] for item in report["issues"]})
                    self.assertTrue(report["passed"])
                    self.assertTrue(report["delivery_verified"])
                    self.assertTrue(report["premiere_conversion_verified"])
                    self.assertEqual(report["schema_version"], 1)
                    self.assertEqual(report["verification_status"], "manual_acceptance_required")
                    self.assertEqual(qa_service.read_report(project, session), report)
                    accepted = qa_service.record_manual_acceptance(
                        session,
                        project,
                        editor="Premiere Pro",
                        editor_version="2026",
                        audio_ok=True,
                        subtitles_ok=True,
                        media_links_ok=True,
                        notes="Opened successfully",
                    )
                    self.assertEqual(accepted["verification_status"], "manually_accepted")
                    self.assertFalse(accepted["manual_acceptance_required"])

                    prproj_path = output / "Story.prproj"
                    original_mtime = prproj_path.stat().st_mtime_ns
                    prproj_path.write_bytes(b"tampered")
                    prproj_path.touch()
                    import os
                    os.utime(prproj_path, ns=(original_mtime, original_mtime))
                    tampered = qa_service.run_quality_check(session, project)
                    self.assertFalse(tampered["premiere_conversion_verified"])
                    self.assertIn(
                        "prproj_conversion_unverified",
                        {item["type"] for item in tampered["issues"]},
                    )
                    prproj_path.write_bytes(b"delivery")
                    conversion = json.loads(conversion_path.read_text(encoding="utf-8"))
                    conversion["prproj_signature"] = qa_service._file_signature(
                        prproj_path, strong=True
                    )
                    conversion_path.write_text(json.dumps(conversion), encoding="utf-8")
                    assignment.scene_offset_start_ms = 250
                    session.add(assignment)
                    session.commit()
                    stale_project_report = qa_service.read_report(project, session)
                    self.assertTrue(stale_project_report["stale"])
                    self.assertFalse(stale_project_report["delivery_verified"])
                    assignment.scene_offset_start_ms = 0
                    session.add(assignment)
                    session.commit()

                    source.unlink()
                    stale_report = qa_service.read_report(project)
                    self.assertFalse(stale_report["passed"])
                    self.assertTrue(stale_report["stale"])
                    report = qa_service.run_quality_check(session, project)
                    missing = next(item for item in report["issues"]
                                   if item["type"] == "source_file_missing")
                    self.assertFalse(report["passed"])
                    self.assertEqual(missing["scene_id"], scene.id)
                    self.assertEqual(missing["file_path"], str(source))

                    (output / "Story.srt").write_text(
                        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n"
                        "2\n00:00:01,000 --> 00:00:02,000\nAlong second subtitle line\n",
                        encoding="utf-8")
                    report = qa_service.run_quality_check(session, project)
                    self.assertIn("subtitle_file_outdated",
                                  {item["type"] for item in report["issues"]})

                    assignment.scene_offset_start_ms = 250
                    session.add(assignment)
                    session.commit()
                    report = qa_service.run_quality_check(session, project)
                    self.assertIn("assignment_invalid",
                                  {item["type"] for item in report["issues"]})
                    self.assertEqual(assignment.scene_offset_start_ms, 250)


if __name__ == "__main__":
    unittest.main()
