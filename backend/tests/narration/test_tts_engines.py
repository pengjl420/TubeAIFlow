import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.models.project import Project
from app.models.narration import Segment
from app.services.narration import tts_service
from app.integrations.tts.cosyvoice_runner import cosyvoice_prompt_text


class TtsEngineTests(unittest.TestCase):
    def test_missing_project_engine_defaults_to_qwen3_tts(self) -> None:
        project = Project(id="p1", name="Qwen default", config_json="{}")

        self.assertEqual(tts_service._project_tts_engine(project), "qwen3_tts")

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
                text="测试",
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
                text="需要合成的文本",
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

    def test_removed_index_engine_is_migrated_to_qwen(self) -> None:
        project = Project(id="p1", name="Legacy", config_json='{"tts_engine": "index_tts"}')

        self.assertEqual(tts_service._project_tts_engine(project), "qwen3_tts")

    def test_chatterbox_configuration_accepts_local_multilingual_v3_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_dir = root / "model"
            model_dir.mkdir()
            for filename in (
                "ve.pt",
                "s3gen.pt",
                "grapheme_mtl_merged_expanded_v1.json",
                "t3_mtl23ls_v3.safetensors",
                "Cangjie5_TC.json",
            ):
                (model_dir / filename).touch()
            python_path = root / "python.exe"
            reference_audio = root / "reference.wav"
            python_path.touch()
            reference_audio.touch()
            settings = SimpleNamespace(
                chatterbox_python=python_path,
                chatterbox_model_dir=model_dir,
                chatterbox_t3_model="v3",
                chatterbox_language="zh",
            )
            project = Project(
                id="p1",
                name="Chatterbox",
                reference_audio_path=str(reference_audio),
                config_json='{"tts_engine": "chatterbox"}',
            )
            segment = Segment(
                id="p1_0001",
                project_id="p1",
                segment_id="0001",
                segment_index=1,
                text="测试",
            )

            with patch.object(tts_service, "get_settings", return_value=settings):
                engine, audio_path = tts_service._validate_configuration(project, [segment])

            self.assertEqual(engine, "chatterbox")
            self.assertEqual(audio_path, reference_audio.resolve())

    def test_chatterbox_runner_command_contains_multilingual_controls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_dir = root / "model"
            python_path = root / "python.exe"
            reference_audio = root / "reference.wav"
            model_dir.mkdir()
            python_path.touch()
            reference_audio.touch()
            settings = SimpleNamespace(
                chatterbox_root=None,
                chatterbox_python=python_path,
                chatterbox_model_dir=model_dir,
                chatterbox_device="cuda",
                chatterbox_language="zh",
                chatterbox_t3_model="v3",
                chatterbox_exaggeration=0.6,
                chatterbox_cfg_weight=0.4,
                chatterbox_temperature=0.8,
            )
            project = Project(id="chatterbox-project", name="Chatterbox")
            segment = Segment(
                id="chatterbox-project_0001",
                project_id="chatterbox-project",
                segment_id="0001",
                segment_index=1,
                text="需要合成的文本",
            )
            completed = SimpleNamespace(returncode=0, stdout="ok", stderr="")

            with (
                patch.object(tts_service, "get_settings", return_value=settings),
                patch.object(tts_service.subprocess, "run", return_value=completed) as run,
            ):
                tts_service._run_chatterbox_batch(
                    project, reference_audio, [segment], root / "audio", root / "logs"
                )

            command = run.call_args.args[0]
            self.assertEqual(command[command.index("--language") + 1], "zh")
            self.assertEqual(command[command.index("--t3-model") + 1], "v3")
            self.assertEqual(command[command.index("--cfg-weight") + 1], "0.4")

    def test_cosyvoice_requires_reference_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cosyvoice_root = root / "CosyVoice"
            model_dir = root / "model"
            python_path = root / "python.exe"
            reference_audio = root / "reference.wav"
            (cosyvoice_root / "cosyvoice").mkdir(parents=True)
            model_dir.mkdir()
            (model_dir / "cosyvoice3.yaml").touch()
            python_path.touch()
            reference_audio.touch()
            settings = SimpleNamespace(
                cosyvoice_root=cosyvoice_root,
                cosyvoice_python=python_path,
                cosyvoice_model_dir=model_dir,
            )
            project = Project(
                id="p1",
                name="CosyVoice",
                reference_audio_path=str(reference_audio),
                config_json='{"tts_engine": "cosyvoice"}',
            )
            segment = Segment(
                id="p1_0001",
                project_id="p1",
                segment_id="0001",
                segment_index=1,
                text="测试",
            )

            with (
                patch.object(tts_service, "get_settings", return_value=settings),
                self.assertRaisesRegex(ValueError, "requires the reference audio transcript"),
            ):
                tts_service._validate_configuration(project, [segment])

    def test_cosyvoice_runner_command_contains_zero_shot_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cosyvoice_root = root / "CosyVoice"
            model_dir = root / "model"
            python_path = root / "python.exe"
            reference_audio = root / "reference.wav"
            cosyvoice_root.mkdir()
            model_dir.mkdir()
            python_path.touch()
            reference_audio.touch()
            settings = SimpleNamespace(
                cosyvoice_root=cosyvoice_root,
                cosyvoice_python=python_path,
                cosyvoice_model_dir=model_dir,
                cosyvoice_instruction="You are helpful.",
                cosyvoice_fp16=True,
            )
            project = Project(
                id="cosyvoice-project",
                name="CosyVoice",
                config_json=json.dumps(
                    {"reference_audio_text": "参考文本", "cosyvoice_speed": 1.1},
                    ensure_ascii=False,
                ),
            )
            segment = Segment(
                id="cosyvoice-project_0001",
                project_id="cosyvoice-project",
                segment_id="0001",
                segment_index=1,
                text="需要合成的文本",
            )
            completed = SimpleNamespace(returncode=0, stdout="ok", stderr="")

            with (
                patch.object(tts_service, "get_settings", return_value=settings),
                patch.object(tts_service.subprocess, "run", return_value=completed) as run,
            ):
                tts_service._run_cosyvoice_batch(
                    project, reference_audio, [segment], root / "audio", root / "logs"
                )

            command = run.call_args.args[0]
            self.assertEqual(command[command.index("--reference-text") + 1], "参考文本")
            self.assertEqual(command[command.index("--speed") + 1], "1.1")
            self.assertIn("--fp16", command)

    def test_cosyvoice3_prompt_includes_instruction_separator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            model_dir = Path(directory)
            (model_dir / "cosyvoice3.yaml").touch()

            prompt = cosyvoice_prompt_text(model_dir, "参考文字", "You are helpful.")

            self.assertEqual(prompt, "You are helpful.<|endofprompt|>参考文字")


if __name__ == "__main__":
    unittest.main()
