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
        self.voice_settings_patch = patch.object(voice_profile_service, "get_settings", return_value=settings)
        self.project_settings_patch = patch.object(project_service, "get_settings", return_value=settings)
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
                text_zh="测试",
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
            session.refresh(project)
            session.refresh(segment)
            config = json.loads(project.config_json or "{}")
            self.assertEqual(config["reference_audio_text"], "更新后的参考文字")
            self.assertEqual(segment.status, "pending")
            self.assertIsNone(segment.audio_path)

            with self.assertRaisesRegex(ValueError, "正被 1 个项目使用"):
                voice_profile_service.delete_profile(session, voice)


if __name__ == "__main__":
    unittest.main()
