import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.models.project import Project
from app.models.narration import Segment
from app.services.narration import tts_service


class TtsEngineTests(unittest.TestCase):
    def test_qwen_configuration_accepts_local_base_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            qwen_root = root / "Qwen3-TTS"
            model_dir = qwen_root / "Base"
            python_path = qwen_root / ".venv" / "python.exe"
            reference_audio = root / "reference.wav"
            (qwen_root / "qwen_tts").mkdir(parents=True)
            model_dir.mkdir()
            python_path.parent.mkdir()
            python_path.touch()
            reference_audio.touch()
            (model_dir / "config.json").write_text(
                json.dumps({"tts_model_type": "base"}),
                encoding="utf-8",
            )
            settings = SimpleNamespace(
                qwen_tts_root=qwen_root,
                qwen_tts_python=python_path,
                qwen_tts_model_dir=model_dir,
            )
            project = Project(
                id="p1",
                name="Qwen",
                reference_audio_path=str(reference_audio),
                config_json='{"tts_engine": "qwen3_tts"}',
            )
            segment = Segment(
                id="p1_0001",
                project_id="p1",
                segment_id="0001",
                segment_index=1,
                text_zh="测试",
            )

            with patch.object(tts_service, "get_settings", return_value=settings):
                engine, audio_path = tts_service._validate_configuration(project, [segment])

            self.assertEqual(engine, "qwen3_tts")
            self.assertEqual(audio_path, reference_audio.resolve())

    def test_qwen_runner_command_contains_clone_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            qwen_root = root / "Qwen3-TTS"
            model_dir = qwen_root / "Base"
            python_path = qwen_root / ".venv" / "python.exe"
            reference_audio = root / "reference.wav"
            audio_dir = root / "audio"
            logs_dir = root / "logs"
            qwen_root.mkdir()
            model_dir.mkdir()
            python_path.parent.mkdir()
            python_path.touch()
            reference_audio.touch()
            settings = SimpleNamespace(
                qwen_tts_root=qwen_root,
                qwen_tts_python=python_path,
                qwen_tts_model_dir=model_dir,
                qwen_tts_device="cuda:0",
                qwen_tts_dtype="bfloat16",
                qwen_tts_language="Chinese",
                qwen_tts_max_new_tokens=2048,
            )
            project = Project(
                id="p1",
                name="Qwen",
                config_json=json.dumps(
                    {"tts_engine": "qwen3_tts", "reference_audio_text": "参考文本"},
                    ensure_ascii=False,
                ),
            )
            segment = Segment(
                id="p1_0001",
                project_id="p1",
                segment_id="0001",
                segment_index=1,
                text_zh="需要合成的文本",
            )

            completed = SimpleNamespace(returncode=0, stdout="ok", stderr="")
            with (
                patch.object(tts_service, "get_settings", return_value=settings),
                patch.object(tts_service.subprocess, "run", return_value=completed) as run,
            ):
                tts_service._run_qwen3_tts_batch(
                    project,
                    reference_audio,
                    [segment],
                    audio_dir,
                    logs_dir,
                )

            command = run.call_args.args[0]
            self.assertIn("--reference-text", command)
            self.assertEqual(command[command.index("--reference-text") + 1], "参考文本")
            self.assertEqual(command[command.index("--dtype") + 1], "bfloat16")
            batch = json.loads((logs_dir / "tts_batch.json").read_text(encoding="utf-8"))
            self.assertEqual(batch[0]["text"], "需要合成的文本")


if __name__ == "__main__":
    unittest.main()
