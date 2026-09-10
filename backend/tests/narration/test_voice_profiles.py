import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

from app.models.narration import Segment
from app.services.narration import voice_profile_service
from app.services.projects import project_service


class VoiceProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.workspace = self.root / "workspace"
        self.engine = create_engine(f"sqlite:///{self.root / 'test.db'}")
        SQLModel.metadata.create_all(self.engine)
        settings = SimpleNamespace(workspace_dir=self.workspace)
        self.voice_settings_patch = patch.object(
            voice_profile_service, "get_settings", return_value=settings
        )
        self.project_settings_patch = patch.object(
            project_service, "get_settings", return_value=settings
        )
        self.voice_settings_patch.start()
        self.project_settings_patch.start()

    def tearDown(self) -> None:
        self.project_settings_patch.stop()
        self.voice_settings_patch.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_project_selects_system_voice_and_profile_update_resets_tts(self) -> None:
        with Session(self.engine) as session:
            voice = voice_profile_service.create_profile(
                session,
                name="纪录片男声",
                tts_engine="qwen3_tts",
                reference_audio_text="原始参考文字",
                source=io.BytesIO(b"first-audio"),
                original_filename="voice.wav",
            )
            self.assertEqual(Path(voice.reference_audio_path).parent.name, "纪录片男声")
            project = project_service.create_project(session, "人物故事")
            project = project_service.update_project_settings(
                session,
                project,
                "人物故事",
                str(self.root / "output"),
                "story",
                "",
                voice_profile_id=voice.id,
            )
            config = json.loads(project.config_json or "{}")
            self.assertEqual(config["voice_profile_id"], voice.id)
            self.assertEqual(config["reference_audio_text"], "原始参考文字")
            self.assertEqual(Path(project.reference_audio_path or "").read_bytes(), b"first-audio")

            segment = Segment(
                id=f"{project.id}_0001",
                project_id=project.id,
                segment_id="0001",
                segment_index=1,
                text="测试",
                status="completed",
                audio_path="old.wav",
                duration=1.0,
            )
            session.add(segment)
            session.commit()

            voice_profile_service.update_profile(
                session,
                voice,
                name="纪录片男声",
                tts_engine="qwen3_tts",
                reference_audio_text="更新后的参考文字",
                source=io.BytesIO(b"second-audio"),
                original_filename="voice.wav",
            )
            self.assertEqual(Path(voice.reference_audio_path).parent.name, "纪录片男声")
            session.refresh(project)
            session.refresh(segment)
            config = json.loads(project.config_json or "{}")
            self.assertEqual(config["reference_audio_text"], "更新后的参考文字")
            self.assertEqual(segment.status, "pending")
            self.assertIsNone(segment.audio_path)

            with self.assertRaisesRegex(ValueError, "正被 1 个项目使用"):
                voice_profile_service.delete_profile(session, voice)

    def test_profile_rename_moves_audio_and_keeps_project_segments(self) -> None:
        with Session(self.engine) as session:
            voice = voice_profile_service.create_profile(
                session,
                name="旧音色",
                tts_engine="qwen3_tts",
                reference_audio_text="",
                source=io.BytesIO(b"audio"),
                original_filename="voice.wav",
            )
            old_path = Path(voice.reference_audio_path)
            project = project_service.create_project(session, "测试项目")
            project_service.update_project_settings(
                session,
                project,
                "测试项目",
                str(self.root / "output"),
                "story",
                "",
                voice_profile_id=voice.id,
            )
            segment = Segment(
                id=f"{project.id}_0001",
                project_id=project.id,
                segment_id="0001",
                segment_index=1,
                text="测试",
                status="completed",
                audio_path="generated.wav",
                duration=1.0,
            )
            session.add(segment)
            session.commit()

            voice_profile_service.update_profile(
                session,
                voice,
                name="新/音色",
                tts_engine="qwen3_tts",
                reference_audio_text="",
            )

            new_path = Path(voice.reference_audio_path)
            session.refresh(project)
            session.refresh(segment)
            self.assertEqual(new_path.parent.name, "新_音色")
            self.assertTrue(new_path.is_file())
            self.assertFalse(old_path.exists())
            self.assertEqual(Path(project.reference_audio_path or ""), new_path)
            self.assertEqual(segment.status, "completed")

    def test_cosyvoice_speed_is_stored_with_voice_and_copied_to_project(self) -> None:
        with Session(self.engine) as session:
            voice = voice_profile_service.create_profile(
                session,
                name="CosyVoice 快速音色",
                tts_engine="cosyvoice",
                reference_audio_text="参考音频文字",
                cosyvoice_speed=1.25,
                source=io.BytesIO(b"audio"),
                original_filename="voice.wav",
            )
            serialized = voice_profile_service.serialize_profile(voice)
            self.assertEqual(serialized["cosyvoice_speed"], 1.25)

            project = project_service.create_project(session, "语速测试")
            project_service.update_project_settings(
                session,
                project,
                "语速测试",
                str(self.root / "output"),
                "story",
                "",
                voice_profile_id=voice.id,
            )

            config = json.loads(project.config_json or "{}")
            self.assertEqual(config["cosyvoice_speed"], 1.25)

    def test_cosyvoice_speed_must_be_in_supported_range(self) -> None:
        with Session(self.engine) as session:
            with self.assertRaisesRegex(ValueError, "0.5 到 2.0"):
                voice_profile_service.create_profile(
                    session,
                    name="无效语速",
                    tts_engine="cosyvoice",
                    reference_audio_text="参考音频文字",
                    cosyvoice_speed=2.1,
                    source=io.BytesIO(b"audio"),
                    original_filename="voice.wav",
                )

    def test_duplicate_profile_copies_audio_and_reports_project_usage(self) -> None:
        with Session(self.engine) as session:
            voice = voice_profile_service.create_profile(
                session,
                name="纪录片旁白",
                tts_engine="qwen3_tts",
                language="yue-HK",
                reference_audio_text="参考文字",
                tags=["旁白", "温和"],
                source=io.BytesIO(b"reference-audio"),
                original_filename="voice.wav",
            )
            project = project_service.create_project(session, "人物项目")
            project_service.update_project_settings(
                session,
                project,
                "人物项目",
                str(self.root / "output"),
                "story",
                "",
                voice_profile_id=voice.id,
            )
            project.status = "narration_in_progress"
            session.add(project)
            session.commit()

            duplicate = voice_profile_service.duplicate_profile(session, voice)
            profiles = {item["id"]: item for item in voice_profile_service.list_profiles(session)}

            self.assertEqual(Path(duplicate.reference_audio_path).read_bytes(), b"reference-audio")
            self.assertNotEqual(duplicate.reference_audio_path, voice.reference_audio_path)
            self.assertEqual(
                voice_profile_service.serialize_profile(duplicate)["tags"], ["旁白", "温和"]
            )
            self.assertEqual(
                voice_profile_service.serialize_profile(duplicate)["language"], "yue-HK"
            )
            self.assertEqual(profiles[voice.id]["usage_count"], 1)
            self.assertEqual(profiles[voice.id]["running_project_count"], 1)
            self.assertEqual(profiles[duplicate.id]["usage_count"], 0)

    def test_language_engine_migration_routes_legacy_english_profile_to_moss(self) -> None:
        with Session(self.engine) as session:
            voice = voice_profile_service.create_profile(
                session,
                name="英文-旧音色",
                tts_engine="cosyvoice",
                language="en-US",
                reference_audio_text="Reference transcript",
                source=io.BytesIO(b"audio"),
                original_filename="voice.wav",
            )
            config = voice_profile_service.load_profile_config(voice)
            config.pop("language")
            voice.config_json = json.dumps(config, ensure_ascii=False)
            session.add(voice)
            session.commit()

            migrated = voice_profile_service.migrate_profile_language_engines(session)

            session.refresh(voice)
            serialized = voice_profile_service.serialize_profile(voice)
            self.assertEqual(migrated, 1)
            self.assertEqual(serialized["language"], "en-US")
            self.assertEqual(serialized["tts_engine"], "moss_tts")


if __name__ == "__main__":
    unittest.main()
