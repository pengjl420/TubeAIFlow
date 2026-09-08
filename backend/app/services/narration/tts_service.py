import json
import logging
import math
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session, select

from app.config import Settings, get_settings
from app.integrations.tts.runner_io import write_json
from app.models.project import Project
from app.providers import TTSProviderRuntime, provider_registry
from app.models.narration import Segment
from app.models.narration import VoiceProfile
from app.infrastructure import gpu_resource, process_runner as task_control
from app.infrastructure.ffmpeg import probe_duration, run_ffmpeg
from app.infrastructure.logging_config import current_task_id, format_task_log, task_log_context
from app.infrastructure.project_layout import ensure_project_dirs, get_project_work_dir, load_project_config
from app.shared.time import utc_now_iso
from app.services.narration import voice_profile_service


logger = logging.getLogger(__name__)


def generate_single_audio(
    task_id: str,
    profile: VoiceProfile,
    text: str,
    output_filename: str,
) -> dict:
    """Generate exactly one audio file without transcript segmentation."""
    with task_log_context(task_id):
        settings = get_settings()
        profile_config = voice_profile_service.load_profile_config(profile)
        output_dir = (settings.workspace_dir / "voice_generations" / task_id).resolve()
        logs_dir = output_dir / "logs"
        output_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)

        project = Project(
            id=f"voice-generation-{task_id}",
            name=profile.name,
            reference_audio_path=profile.reference_audio_path,
            config_json=json.dumps(
                {
                    "tts_engine": str(profile_config.get("tts_engine") or "qwen3_tts"),
                    "voice_language": voice_profile_service.profile_language(profile_config),
                    "reference_audio_text": str(profile_config.get("reference_audio_text") or ""),
                    "cosyvoice_speed": voice_profile_service.profile_cosyvoice_speed(profile_config),
                },
                ensure_ascii=False,
            ),
        )
        segment = Segment(
            id=task_id,
            segment_id=Path(output_filename).stem,
            project_id=project.id,
            segment_index=1,
            text=text,
        )
        engine, reference_audio_path = _validate_configuration(project, [segment])
        output_path = output_dir / output_filename
        output_path.unlink(missing_ok=True)
        _write_initial_progress(logs_dir / "tts_progress.json", [segment])
        _run_tts_batch(engine, project, reference_audio_path, [segment], output_dir, logs_dir)
        if not output_path.is_file():
            raise RuntimeError(f"{_engine_label(engine)} did not create the requested audio file")
        duration = probe_duration(output_path)
        return {"output_path": str(output_path), "duration": duration}


def generate_segmented_audio(
    task_id: str,
    profile: VoiceProfile,
    texts: list[str],
    output_filename: str,
) -> dict:
    """Generate one WAV per non-empty transcript line, then merge them in order."""
    with task_log_context(task_id):
        if not texts:
            raise ValueError("逐字稿按换行切分后没有可生成的文本")

        settings = get_settings()
        profile_config = voice_profile_service.load_profile_config(profile)
        output_dir = (settings.workspace_dir / "voice_generations" / task_id).resolve()
        segment_dir = output_dir / "segments"
        logs_dir = output_dir / "logs"
        segment_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)

        output_stem = Path(output_filename).stem
        project = Project(
            id=f"voice-generation-{task_id}",
            name=profile.name,
            reference_audio_path=profile.reference_audio_path,
            config_json=json.dumps(
                {
                    "tts_engine": str(profile_config.get("tts_engine") or "qwen3_tts"),
                    "voice_language": voice_profile_service.profile_language(profile_config),
                    "reference_audio_text": str(profile_config.get("reference_audio_text") or ""),
                    "cosyvoice_speed": voice_profile_service.profile_cosyvoice_speed(profile_config),
                },
                ensure_ascii=False,
            ),
        )
        segments = [
            Segment(
                id=f"{task_id}-{index:04d}",
                segment_id=f"{output_stem}_{index:04d}",
                project_id=project.id,
                segment_index=index,
                text=content,
            )
            for index, content in enumerate(texts, start=1)
        ]
        engine, reference_audio_path = _validate_configuration(project, segments)
        logger.info("TTS configuration validated: provider=%s segments=%s", engine, len(segments))
        for segment in segments:
            (segment_dir / f"{segment.segment_id}.wav").unlink(missing_ok=True)
        _write_initial_progress(logs_dir / "tts_progress.json", segments)
        _run_tts_batch(engine, project, reference_audio_path, segments, segment_dir, logs_dir)

        segment_results = []
        for segment in segments:
            segment_path = segment_dir / f"{segment.segment_id}.wav"
            if not segment_path.is_file():
                raise RuntimeError(f"{_engine_label(engine)} 未生成分段音频：{segment_path.name}")
            segment_results.append(
                {
                    "index": segment.segment_index,
                    "text": segment.text,
                    "filename": segment_path.name,
                    "output_path": str(segment_path),
                    "duration": probe_duration(segment_path),
                }
            )
            logger.info(
                "TTS segment ready: segment=%s duration=%.3fs",
                segment.segment_id, segment_results[-1]["duration"],
            )

        output_path = output_dir / output_filename
        output_path.unlink(missing_ok=True)
        concat_path = logs_dir / "segments.txt"
        concat_path.write_text(
            "\n".join(
                "file '" + Path(item["output_path"]).as_posix().replace("'", r"'\''") + "'"
                for item in segment_results
            ),
            encoding="utf-8",
        )
        logger.info("Audio merge started: segments=%s", len(segment_results))
        run_ffmpeg([
            "-y", "-f", "concat", "-safe", "0", "-i", str(concat_path),
            "-c", "copy", str(output_path),
        ])
        if not output_path.is_file():
            raise RuntimeError("FFmpeg 未生成合并后的完整音频")

        result = {
            "output_path": str(output_path),
            "duration": probe_duration(output_path),
            "segments": segment_results,
        }
        (output_dir / "segments.json").write_text(
            json.dumps(segment_results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("Audio merge completed: duration=%.3fs", result["duration"])
        return result


def generate_project_tts(session: Session, project: Project) -> list[Segment]:
    settings = get_settings()
    segments = list(
        session.exec(
            select(Segment)
            .where(Segment.project_id == project.id)
            .order_by(Segment.segment_index)
        ).all()
    )
    engine, reference_audio_path = _validate_configuration(project, segments)

    base_dir = get_project_work_dir(project, settings.workspace_dir)
    ensure_project_dirs(base_dir)
    audio_dir = base_dir / "audio" / "segments"
    audio_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = base_dir / "logs"
    recovered = _recover_completed_segments(session, segments, audio_dir, logs_dir)
    if recovered:
        logger.info("Recovered %s completed TTS segment(s) for project %s", recovered, project.id)
    pending = [
        item
        for item in segments
        if item.status != "completed" or not (audio_dir / f"{item.segment_id}.wav").is_file()
    ]

    project.status = "tts_running"
    session.add(project)
    session.commit()

    if pending:
        # A pending segment may still have an older WAV after its text was edited.
        # Remove it so a failed regeneration cannot be mistaken for a new result.
        for segment in pending:
            (audio_dir / f"{segment.segment_id}.wav").unlink(missing_ok=True)
        _write_initial_progress(logs_dir / "tts_progress.json", pending)
        try:
            _run_tts_batch(engine, project, reference_audio_path, pending, audio_dir, logs_dir)
        except Exception:
            _recover_completed_segments(session, pending, audio_dir, logs_dir)
            raise

    result_path = base_dir / "logs" / "tts_results.json"
    result_by_id = {}
    if result_path.exists():
        result_by_id = {
            item["segment_id"]: item
            for item in json.loads(result_path.read_text(encoding="utf-8"))
        }

    for segment in segments:
        output_path = audio_dir / f"{segment.segment_id}.wav"
        result = result_by_id.get(segment.segment_id, {})
        if output_path.exists():
            segment.audio_path = str(output_path)
            segment.duration = probe_duration(output_path)
            segment.status = "completed"
            segment.error_message = None
        else:
            segment.status = "failed"
            segment.error_message = result.get("error", f"{_engine_label(engine)} did not create an audio file")
        segment.updated_at = datetime.utcnow().isoformat()
        session.add(segment)

    project.status = "failed" if any(item.status == "failed" for item in segments) else "tts_completed"
    project.updated_at = datetime.utcnow().isoformat()
    session.add(project)
    session.commit()
    return segments


def regenerate_segment_tts(session: Session, project: Project, segment: Segment) -> Segment:
    settings = get_settings()
    engine, reference_audio_path = _validate_configuration(project, [segment])
    base_dir = get_project_work_dir(project, settings.workspace_dir)
    ensure_project_dirs(base_dir)
    audio_dir = base_dir / "audio" / "segments"
    audio_dir.mkdir(parents=True, exist_ok=True)

    output_path = audio_dir / f"{segment.segment_id}.wav"
    output_path.unlink(missing_ok=True)
    segment.audio_path = None
    segment.duration = None
    segment.start_time = None
    segment.end_time = None
    segment.status = "tts_running"
    segment.error_message = None
    segment.updated_at = datetime.utcnow().isoformat()
    session.add(segment)
    session.commit()

    logs_dir = base_dir / "logs"
    _write_initial_progress(logs_dir / "tts_progress.json", [segment])
    _run_tts_batch(engine, project, reference_audio_path, [segment], audio_dir, logs_dir)

    result_path = base_dir / "logs" / "tts_results.json"
    result = {}
    if result_path.exists():
        for item in json.loads(result_path.read_text(encoding="utf-8")):
            if item.get("segment_id") == segment.segment_id:
                result = item
                break

    if output_path.exists():
        segment.audio_path = str(output_path)
        segment.duration = probe_duration(output_path)
        segment.status = "completed"
        segment.error_message = None
    else:
        segment.status = "failed"
        segment.error_message = result.get("error", f"{_engine_label(engine)} did not create an audio file")
    segment.updated_at = datetime.utcnow().isoformat()
    session.add(segment)
    session.commit()
    session.refresh(segment)
    return segment


def _validate_configuration(project: Project, segments: list[Segment]) -> tuple[str, Path]:
    settings = get_settings()
    if not segments:
        raise ValueError("Please create transcript segments before starting TTS")
    reference_audio_path = _project_reference_audio_path(project)
    if reference_audio_path is None:
        raise ValueError("请先配置项目参考音频后再开始 TTS")
    if not reference_audio_path.is_file():
        raise ValueError("项目配置的参考音频文件不存在，请重新上传参考音频")
    engine = _project_tts_engine(project)
    required_paths = _required_engine_paths(settings, engine)
    for name, path in required_paths.items():
        if path is None or not path.exists():
            raise ValueError(f"{name} is not configured or does not exist: {path}")
    _validate_engine_assets(settings, project, engine)
    return engine, reference_audio_path


def _required_engine_paths(settings: Settings, engine: str) -> dict[str, Path | None]:
    return provider_registry.runtime(engine, TTSProviderRuntime).required_paths(settings)


def _validate_engine_assets(settings: Settings, project: Project, engine: str) -> None:
    provider_registry.runtime(engine, TTSProviderRuntime).validate_assets(settings, project)


def _validate_qwen_assets(settings: Settings) -> None:
    if not (settings.qwen_tts_root / "qwen_tts").is_dir():
        raise ValueError("Qwen3-TTS source package is missing under qwen_tts_root")
    model_config_path = settings.qwen_tts_model_dir / "config.json"
    if not model_config_path.is_file():
        raise ValueError("Qwen3-TTS model config is missing")
    try:
        model_config = json.loads(model_config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Qwen3-TTS model config cannot be read") from exc
    if model_config.get("tts_model_type") != "base":
        raise ValueError("Qwen3-TTS voice cloning requires a Base model")


def _validate_cosyvoice_assets(settings: Settings, project: Project) -> None:
    if not (settings.cosyvoice_root / "cosyvoice").is_dir():
        raise ValueError("CosyVoice source package is missing under cosyvoice_root")
    model_configs = ("cosyvoice3.yaml", "cosyvoice2.yaml", "cosyvoice.yaml")
    if not any((settings.cosyvoice_model_dir / name).is_file() for name in model_configs):
        raise ValueError("CosyVoice model config is missing")
    if not _project_reference_audio_text(project):
        raise ValueError("CosyVoice zero-shot voice cloning requires the reference audio transcript")


def _validate_index_assets(settings: Settings) -> None:
    if not (settings.index_tts_root / "indextts" / "infer.py").is_file():
        raise ValueError("IndexTTS source package is missing")
    for name in ("bigvgan_generator.pth", "bpe.model", "gpt.pth", "config.yaml"):
        if not (settings.index_tts_model_dir / name).is_file():
            raise ValueError(f"IndexTTS model file is missing: {name}")


def _validate_moss_assets(settings: Settings) -> None:
    if not (settings.moss_tts_root / "moss_tts_local_v1.5" / "streaming.py").is_file():
        raise ValueError("MOSS-TTS Local v1.5 source package is missing")
    if not (settings.moss_tts_model_dir / "config.json").is_file():
        raise ValueError("MOSS-TTS model config is missing")
    if not (settings.moss_tts_codec_dir / "config.json").is_file():
        raise ValueError("MOSS-TTS audio tokenizer config is missing")


def _project_tts_engine(project: Project) -> str:
    engine = str(load_project_config(project).get("tts_engine") or "qwen3_tts").strip().lower()
    return engine


def _project_reference_audio_text(project: Project) -> str:
    return str(load_project_config(project).get("reference_audio_text") or "").strip()


def _project_voice_language(project: Project) -> str:
    return str(load_project_config(project).get("voice_language") or "zh-CN").strip()


def _project_cosyvoice_speed(project: Project) -> float:
    value = load_project_config(project).get("cosyvoice_speed", 1.0)
    try:
        speed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("CosyVoice voice speed must be a number") from exc
    if not math.isfinite(speed) or not 0.5 <= speed <= 2.0:
        raise ValueError("CosyVoice voice speed must be between 0.5 and 2.0")
    return speed


def _engine_label(engine: str) -> str:
    try:
        return provider_registry.get(engine).display_name
    except ValueError:
        return engine


def _project_reference_audio_path(project: Project) -> Path | None:
    if project.reference_audio_path:
        return Path(project.reference_audio_path).resolve()
    if not project.config_json:
        return None
    try:
        config = json.loads(project.config_json)
    except json.JSONDecodeError:
        return None
    reference_audio_path = config.get("reference_audio_path") if isinstance(config, dict) else None
    return Path(reference_audio_path).resolve() if reference_audio_path else None


def _run_tts_batch(
    engine: str,
    project: Project,
    reference_audio_path: Path,
    segments: list[Segment],
    audio_dir: Path,
    logs_dir: Path,
) -> None:
    logger.info("TTS batch waiting for GPU: provider=%s segments=%s", engine, len(segments))
    with gpu_resource.exclusive_gpu(f"tts:{engine}:project:{project.id}"):
        logger.info("TTS batch started: provider=%s", engine)
        provider_registry.runtime(engine, TTSProviderRuntime).synthesize_batch(
            project, reference_audio_path, segments, audio_dir, logs_dir
        )
    logger.info("TTS batch completed: provider=%s", engine)


def _run_qwen3_tts_batch(
    project: Project,
    reference_audio_path: Path,
    segments: list[Segment],
    audio_dir: Path,
    logs_dir: Path,
) -> None:
    settings = get_settings()
    batch_path, result_path, progress_path = _prepare_batch_files(segments, audio_dir, logs_dir)
    runner_path = (Path(__file__).parents[2] / "integrations" / "tts" / "qwen3_tts_runner.py").resolve()
    command = [
        str(settings.qwen_tts_python),
        "-s",
        str(runner_path),
        "--qwen-root",
        str(settings.qwen_tts_root.resolve()),
        "--model-dir",
        str(settings.qwen_tts_model_dir.resolve()),
        "--batch-file",
        str(batch_path),
        "--voice",
        str(reference_audio_path.resolve()),
        "--reference-text",
        _project_reference_audio_text(project),
        "--result-file",
        str(result_path),
        "--progress-file",
        str(progress_path),
        "--device",
        settings.qwen_tts_device,
        "--dtype",
        settings.qwen_tts_dtype,
        "--language",
        settings.qwen_tts_language,
        "--max-new-tokens",
        str(settings.qwen_tts_max_new_tokens),
    ]
    _execute_batch_runner(project.id, command, settings.qwen_tts_root, logs_dir, result_path, "Qwen3-TTS")


def _run_cosyvoice_batch(
    project: Project,
    reference_audio_path: Path,
    segments: list[Segment],
    audio_dir: Path,
    logs_dir: Path,
) -> None:
    settings = get_settings()
    batch_path, result_path, progress_path = _prepare_batch_files(segments, audio_dir, logs_dir)
    runner_path = (Path(__file__).parents[2] / "integrations" / "tts" / "cosyvoice_runner.py").resolve()
    command = [
        str(settings.cosyvoice_python),
        "-s",
        str(runner_path),
        "--cosyvoice-root",
        str(settings.cosyvoice_root.resolve()),
        "--model-dir",
        str(settings.cosyvoice_model_dir.resolve()),
        "--batch-file",
        str(batch_path),
        "--voice",
        str(reference_audio_path.resolve()),
        "--reference-text",
        _project_reference_audio_text(project),
        "--result-file",
        str(result_path),
        "--progress-file",
        str(progress_path),
        "--speed",
        str(_project_cosyvoice_speed(project)),
        "--instruction",
        settings.cosyvoice_instruction,
        "--max-attempts",
        str(settings.cosyvoice_max_attempts),
        "--seed-round",
        str(_next_cosyvoice_seed_round(logs_dir)),
        "--min-chars-per-second",
        str(settings.cosyvoice_min_chars_per_second),
        "--duration-slack-seconds",
        str(settings.cosyvoice_duration_slack_seconds),
        "--duration-outlier-ratio",
        str(settings.cosyvoice_duration_outlier_ratio),
    ]
    if settings.cosyvoice_fp16:
        command.append("--fp16")
    cosyvoice_cache = settings.cosyvoice_root / "model_cache"
    _execute_batch_runner(
        project.id,
        command,
        settings.cosyvoice_root,
        logs_dir,
        result_path,
        "CosyVoice",
        env_overrides={
            "MODELSCOPE_CACHE": str(cosyvoice_cache / "modelscope"),
            "HF_HOME": str(cosyvoice_cache / "huggingface"),
        },
    )


def _next_cosyvoice_seed_round(logs_dir: Path) -> int:
    """Use archived completed runs to keep retries reproducible but non-repeating."""
    return len(list(logs_dir.glob("tts_*.log")))


def _run_index_tts_batch(
    project: Project,
    reference_audio_path: Path,
    segments: list[Segment],
    audio_dir: Path,
    logs_dir: Path,
) -> None:
    settings = get_settings()
    batch_path, result_path, progress_path = _prepare_batch_files(segments, audio_dir, logs_dir)
    runner_path = (Path(__file__).parents[2] / "integrations" / "tts" / "index_tts_runner.py").resolve()
    command = [
        str(settings.index_tts_python), "-s", str(runner_path),
        "--index-root", str(settings.index_tts_root.resolve()),
        "--model-dir", str(settings.index_tts_model_dir.resolve()),
        "--batch-file", str(batch_path),
        "--voice", str(reference_audio_path.resolve()),
        "--result-file", str(result_path),
        "--progress-file", str(progress_path),
        "--max-text-tokens", str(settings.index_tts_max_text_tokens_per_sentence),
    ]
    _execute_batch_runner(project.id, command, settings.index_tts_root, logs_dir, result_path, "IndexTTS")


def _run_moss_tts_batch(
    project: Project,
    reference_audio_path: Path,
    segments: list[Segment],
    audio_dir: Path,
    logs_dir: Path,
) -> None:
    settings = get_settings()
    if _project_voice_language(project) != "en-US":
        raise ValueError("MOSS-TTS is configured for English voice profiles")
    batch_path, result_path, progress_path = _prepare_batch_files(segments, audio_dir, logs_dir)
    runner_path = (Path(__file__).parents[2] / "integrations" / "tts" / "moss_tts_runner.py").resolve()
    command = [
        str(settings.moss_tts_python), "-s", str(runner_path),
        "--moss-root", str(settings.moss_tts_root.resolve()),
        "--model-dir", str(settings.moss_tts_model_dir.resolve()),
        "--codec-dir", str(settings.moss_tts_codec_dir.resolve()),
        "--batch-file", str(batch_path),
        "--voice", str(reference_audio_path.resolve()),
        "--result-file", str(result_path),
        "--progress-file", str(progress_path),
        "--device", settings.moss_tts_device,
        "--dtype", settings.moss_tts_dtype,
        "--max-new-tokens", str(settings.moss_tts_max_new_tokens),
    ]
    _execute_batch_runner(
        project.id,
        command,
        settings.moss_tts_root,
        logs_dir,
        result_path,
        "MOSS-TTS",
        env_overrides={
            "HF_HOME": str(settings.moss_tts_root / "models" / "cache"),
            "HF_HUB_OFFLINE": "1",
            "HF_HUB_DISABLE_XET": "1",
        },
    )


def _prepare_batch_files(
    segments: list[Segment], audio_dir: Path, logs_dir: Path
) -> tuple[Path, Path, Path]:
    audio_dir = audio_dir.resolve()
    logs_dir = logs_dir.resolve()
    logs_dir.mkdir(parents=True, exist_ok=True)
    batch_path = logs_dir / "tts_batch.json"
    result_path = logs_dir / "tts_results.json"
    progress_path = logs_dir / "tts_progress.json"
    result_path.unlink(missing_ok=True)
    batch_path.write_text(
        json.dumps(
            [
                {
                    "segment_id": item.segment_id,
                    "text": item.text,
                    "output_path": str(audio_dir / f"{item.segment_id}.wav"),
                }
                for item in segments
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return batch_path, result_path, progress_path


def _recover_completed_segments(
    session: Session,
    segments: list[Segment],
    audio_dir: Path,
    logs_dir: Path,
) -> int:
    """Recover valid WAVs produced by an interrupted batch with unchanged text."""
    batch_path = logs_dir / "tts_batch.json"
    if not batch_path.is_file():
        return 0
    try:
        batch = json.loads(batch_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if not isinstance(batch, list):
        return 0
    previous_by_id = {
        str(item.get("segment_id")): item
        for item in batch
        if isinstance(item, dict) and item.get("segment_id")
    }
    recovered = 0
    now = utc_now_iso()
    for segment in segments:
        if segment.status == "completed":
            continue
        previous = previous_by_id.get(segment.segment_id)
        output_path = (audio_dir / f"{segment.segment_id}.wav").resolve()
        if (
            not previous
            or previous.get("text") != segment.text
            or not previous.get("output_path")
            or Path(previous["output_path"]).resolve() != output_path
            or not output_path.is_file()
        ):
            continue
        try:
            duration = probe_duration(output_path)
        except Exception as exc:
            logger.warning("Ignoring invalid recovered TTS audio %s: %s", output_path, exc)
            continue
        if duration <= 0:
            continue
        segment.audio_path = str(output_path)
        segment.duration = duration
        segment.status = "completed"
        segment.error_message = None
        segment.updated_at = now
        session.add(segment)
        recovered += 1
    if recovered:
        session.commit()
    return recovered


def _execute_batch_runner(
    project_id: str,
    command: list[str],
    cwd: Path,
    logs_dir: Path,
    result_path: Path,
    engine_label: str,
    env_overrides: dict[str, str] | None = None,
) -> None:
    logs_dir = logs_dir.resolve()

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    if env_overrides:
        env.update(env_overrides)
    if current_task_id():
        env["TUBEAIFOLW_TASK_ID"] = current_task_id()
    logger.info("TTS runner started: provider=%s", engine_label)
    result = _run_controlled_process(
        project_id,
        command,
        cwd=cwd.resolve(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=env,
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    stdout_log = format_task_log(result.stdout)
    (logs_dir / "tts.log").write_text(stdout_log, encoding="utf-8")
    (logs_dir / f"tts_{timestamp}.log").write_text(stdout_log, encoding="utf-8")
    if result.stderr:
        stderr_log = format_task_log(result.stderr)
        (logs_dir / "error.log").write_text(stderr_log, encoding="utf-8")
        (logs_dir / f"error_{timestamp}.log").write_text(stderr_log, encoding="utf-8")
    logger.info("TTS runner exited: provider=%s returncode=%s", engine_label, result.returncode)
    # Preserve child output before propagating a user pause/cancellation.
    task_control.check_cancelled(project_id)
    if result.returncode != 0 and not result_path.exists():
        message = result.stderr.strip() or result.stdout.strip() or f"{engine_label} batch failed"
        raise RuntimeError(message[-4000:])


def _run_controlled_process(project_id: str, command: list[str], **kwargs) -> subprocess.CompletedProcess:
    if not task_control.status(project_id)["running"]:
        return subprocess.run(command, **kwargs)
    task_control.check_cancelled(project_id)
    kwargs.pop("check", None)
    if kwargs.pop("capture_output", False):
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    process = subprocess.Popen(command, **kwargs)
    task_control.register_process(project_id, process)
    try:
        stdout, stderr = process.communicate()
    finally:
        task_control.unregister_process(project_id, process)
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _write_initial_progress(progress_path: Path, segments: list[Segment]) -> None:
    segment_ids = [item.segment_id for item in segments]
    data = {
        "total": len(segments),
        "completed": 0,
        "failed": 0,
        "current_segment_id": None,
        "status": "running",
        "segment_ids": segment_ids,
        "segment_results": [],
    }
    write_json(progress_path, data)


def _bind_tts_provider_runtimes() -> None:
    """Bind existing local runners behind the executable provider contract."""
    adapters = {
        "tts.qwen3_tts": TTSProviderRuntime(
            required_paths=lambda settings: {
                "QWEN_TTS_ROOT": settings.qwen_tts_root,
                "QWEN_TTS_PYTHON": settings.qwen_tts_python,
                "QWEN_TTS_MODEL_DIR": settings.qwen_tts_model_dir,
            },
            validate_assets=lambda settings, _project: _validate_qwen_assets(settings),
            synthesize_batch=lambda *args: _run_qwen3_tts_batch(*args),
        ),
        "tts.cosyvoice": TTSProviderRuntime(
            required_paths=lambda settings: {
                "COSYVOICE_ROOT": settings.cosyvoice_root,
                "COSYVOICE_PYTHON": settings.cosyvoice_python,
                "COSYVOICE_MODEL_DIR": settings.cosyvoice_model_dir,
            },
            validate_assets=_validate_cosyvoice_assets,
            synthesize_batch=lambda *args: _run_cosyvoice_batch(*args),
        ),
        "tts.index_tts": TTSProviderRuntime(
            required_paths=lambda settings: {
                "INDEX_TTS_ROOT": settings.index_tts_root,
                "INDEX_TTS_PYTHON": settings.index_tts_python,
                "INDEX_TTS_MODEL_DIR": settings.index_tts_model_dir,
            },
            validate_assets=lambda settings, _project: _validate_index_assets(settings),
            synthesize_batch=lambda *args: _run_index_tts_batch(*args),
        ),
        "tts.moss_tts": TTSProviderRuntime(
            required_paths=lambda settings: {
                "MOSS_TTS_ROOT": settings.moss_tts_root,
                "MOSS_TTS_PYTHON": settings.moss_tts_python,
                "MOSS_TTS_MODEL_DIR": settings.moss_tts_model_dir,
                "MOSS_TTS_CODEC_DIR": settings.moss_tts_codec_dir,
            },
            validate_assets=lambda settings, _project: _validate_moss_assets(settings),
            synthesize_batch=lambda *args: _run_moss_tts_batch(*args),
        ),
    }
    for provider_id, runtime in adapters.items():
        provider_registry.bind_runtime(provider_id, runtime)


_bind_tts_provider_runtimes()
