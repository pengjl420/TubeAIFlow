import json
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

from app.config import get_settings
from app.models.project import Project
from app.models.segment import Segment
from app.services import srt_service
from app.utils.ffmpeg_utils import probe_duration
from app.utils.project_paths import ensure_project_dirs, get_project_work_dir, load_project_config


logger = logging.getLogger(__name__)


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
        logs_dir = base_dir / "logs"
        _write_initial_progress(logs_dir / "tts_progress.json", pending)
        _run_tts_batch(engine, project, reference_audio_path, pending, audio_dir, logs_dir)

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
            srt_service.create_segment_srt(project, segment)
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
        srt_service.create_segment_srt(project, segment)
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
    if engine == "index_tts":
        required_paths = {
            "INDEX_TTS_ROOT": settings.index_tts_root,
            "INDEX_TTS_PYTHON": settings.index_tts_python,
            "INDEX_TTS_MODEL_DIR": settings.index_tts_model_dir,
        }
    elif engine == "qwen3_tts":
        required_paths = {
            "QWEN_TTS_ROOT": settings.qwen_tts_root,
            "QWEN_TTS_PYTHON": settings.qwen_tts_python,
            "QWEN_TTS_MODEL_DIR": settings.qwen_tts_model_dir,
        }
    else:
        raise ValueError(f"Unsupported TTS engine: {engine}")

    for name, path in required_paths.items():
        if path is None or not path.exists():
            raise ValueError(f"{name} is not configured or does not exist: {path}")
    if engine == "index_tts":
        if not (settings.index_tts_model_dir / "config.yaml").is_file():
            raise ValueError("IndexTTS model config is missing")
    else:
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
    return engine, reference_audio_path


def _project_tts_engine(project: Project) -> str:
    return str(load_project_config(project).get("tts_engine") or "index_tts").strip().lower()


def _project_reference_audio_text(project: Project) -> str:
    return str(load_project_config(project).get("reference_audio_text") or "").strip()


def _engine_label(engine: str) -> str:
    return "Qwen3-TTS" if engine == "qwen3_tts" else "IndexTTS"


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
    if engine == "index_tts":
        _run_index_tts_batch(reference_audio_path, segments, audio_dir, logs_dir)
        return
    if engine == "qwen3_tts":
        _run_qwen3_tts_batch(project, reference_audio_path, segments, audio_dir, logs_dir)
        return
    raise ValueError(f"Unsupported TTS engine: {engine}")


def _run_index_tts_batch(
    reference_audio_path: Path,
    segments: list[Segment],
    audio_dir: Path,
    logs_dir: Path,
) -> None:
    settings = get_settings()
    reference_audio_path = reference_audio_path.resolve()
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
                    "text": item.text_zh,
                    "output_path": str(audio_dir / f"{item.segment_id}.wav"),
                }
                for item in segments
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    runner_path = Path(__file__).with_name("index_tts_v1_runner.py").resolve()
    command = [
        str(settings.index_tts_python),
        "-s",
        str(runner_path),
        "--index-root",
        str(settings.index_tts_root.resolve()),
        "--model-dir",
        str(settings.index_tts_model_dir.resolve()),
        "--batch-file",
        str(batch_path),
        "--voice",
        str(reference_audio_path),
        "--result-file",
        str(result_path),
        "--progress-file",
        str(progress_path),
    ]
    if settings.index_tts_fp16:
        command.append("--fp16")

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    result = subprocess.run(
        command,
        cwd=settings.index_tts_root.resolve(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=env,
    )
    (logs_dir / "tts.log").write_text(result.stdout, encoding="utf-8")
    if result.stderr:
        (logs_dir / "error.log").write_text(result.stderr, encoding="utf-8")
    if result.returncode != 0 and not result_path.exists():
        message = result.stderr.strip() or result.stdout.strip() or "IndexTTS batch failed"
        raise RuntimeError(message[-4000:])


def _run_qwen3_tts_batch(
    project: Project,
    reference_audio_path: Path,
    segments: list[Segment],
    audio_dir: Path,
    logs_dir: Path,
) -> None:
    settings = get_settings()
    reference_audio_path = reference_audio_path.resolve()
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
                    "text": item.text_zh,
                    "output_path": str(audio_dir / f"{item.segment_id}.wav"),
                }
                for item in segments
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    runner_path = Path(__file__).with_name("qwen3_tts_runner.py").resolve()
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
        str(reference_audio_path),
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

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    result = subprocess.run(
        command,
        cwd=settings.qwen_tts_root.resolve(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=env,
    )
    (logs_dir / "tts.log").write_text(result.stdout, encoding="utf-8")
    if result.stderr:
        (logs_dir / "error.log").write_text(result.stderr, encoding="utf-8")
    if result.returncode != 0 and not result_path.exists():
        message = result.stderr.strip() or result.stdout.strip() or "Qwen3-TTS batch failed"
        raise RuntimeError(message[-4000:])


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
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = progress_path.with_suffix(progress_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(progress_path)
