import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.models.project import Project
from app.models.narration import Segment
from app.services.narration import tts_service
from app.integrations.tts.cosyvoice_runner import (
    cosyvoice_prompt_text,
    duration_quality,
    segment_attempt_seed,
    spoken_character_count,
)


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
                cosyvoice_max_attempts=3,
                cosyvoice_min_chars_per_second=2.8,
                cosyvoice_duration_slack_seconds=2.0,
                cosyvoice_duration_outlier_ratio=1.45,
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
            self.assertEqual(command[command.index("--max-attempts") + 1], "3")
            self.assertIn("--fp16", command)

    def test_cosyvoice_seed_is_stable_and_attempt_specific(self) -> None:
        first = segment_attempt_seed("0192", "第一次只談錢", 1)

        self.assertEqual(first, segment_attempt_seed("0192", "第一次只談錢", 1))
        self.assertNotEqual(first, segment_attempt_seed("0192", "第一次只談錢", 2))
        self.assertNotEqual(first, segment_attempt_seed("0193", "第一次只談錢", 1))

    def test_cosyvoice_duration_quality_rejects_hallucination_outlier(self) -> None:
        suspicious, reason, _ = duration_quality(
            "第一次只談錢，將各自收入、債務、日常支出，同幫助仔女嘅界線，坦白而完整咁說明。",
            14.4,
            [0.25, 0.24, 0.26, 0.23, 0.25],
            min_chars_per_second=2.8,
            duration_slack_seconds=2.0,
            duration_outlier_ratio=1.45,
        )

        self.assertTrue(suspicious)
        self.assertIn("duration", reason)

    def test_cosyvoice_duration_quality_accepts_normal_audio(self) -> None:
        suspicious, reason, ratio = duration_quality(
            "第一次只談錢，將各自收入、債務、日常支出，同幫助仔女嘅界線，坦白而完整咁說明。",
            9.1,
            [0.25, 0.24, 0.26, 0.23, 0.25],
            min_chars_per_second=2.8,
            duration_slack_seconds=2.0,
            duration_outlier_ratio=1.45,
        )

        self.assertFalse(suspicious)
        self.assertIsNone(reason)
        self.assertGreater(ratio, 0)

    def test_cosyvoice_spoken_length_expands_ascii_digits(self) -> None:
        text = "His first marriage ended in the early 1950s."

        self.assertEqual(spoken_character_count(text), 48)

    def test_cosyvoice_duration_quality_accepts_normal_year_audio(self) -> None:
        text = "His first marriage ended in the early 1950s."
        recent_ratio = 3.08 / 36

        suspicious, reason, _ = duration_quality(
            text,
            5.6,
            [recent_ratio] * 5,
            min_chars_per_second=2.8,
            duration_slack_seconds=2.0,
            duration_outlier_ratio=1.45,
        )

        self.assertFalse(suspicious)
        self.assertIsNone(reason)

    def test_cosyvoice_duration_quality_still_rejects_numeric_hallucination(self) -> None:
        text = "His first marriage ended in the early 1950s."
        recent_ratio = 3.08 / 36

        suspicious, reason, _ = duration_quality(
            text,
            12.0,
            [recent_ratio] * 5,
            min_chars_per_second=2.8,
            duration_slack_seconds=2.0,
            duration_outlier_ratio=1.45,
        )

        self.assertTrue(suspicious)
        self.assertIn("outlier", reason)

    def test_cosyvoice3_prompt_includes_instruction_separator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            model_dir = Path(directory)
            (model_dir / "cosyvoice3.yaml").touch()

            prompt = cosyvoice_prompt_text(model_dir, "参考文字", "You are helpful.")

            self.assertEqual(prompt, "You are helpful.<|endofprompt|>参考文字")


if __name__ == "__main__":
    unittest.main()
