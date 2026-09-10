import json
from pathlib import Path

from app.config import get_settings
from app.models.project import Project
from app.models.narration import Segment
from app.infrastructure.project_layout import (
    ensure_project_dirs,
    get_final_srt_path,
    get_output_stem,
    get_project_work_dir,
)
from app.shared.time import seconds_to_srt_time
from app.services.narration import subtitle_service
from app.services.narration import alignment_service
from app.infrastructure.project_layout import load_project_config
from app.infrastructure.atomic_files import write_json_atomic, write_text_atomic


def create_full_srt(
    project: Project,
    segments: list[Segment],
    session=None,
) -> Path:
    base_dir = get_project_work_dir(project, get_settings().workspace_dir)
    ensure_project_dirs(base_dir)

    settings = get_settings()
    cues, alignment = _build_aligned_cues(project, segments, settings)
    if session is not None:
        subtitle_service.replace_project_cues(session, project.id, cues)

    stem = get_output_stem(project)
    work_path = base_dir / "subtitles" / f"{stem}.srt"
    _write_srt(
        work_path,
        [(item["start_ms"] / 1000, item["end_ms"] / 1000, item["text"]) for item in cues],
    )

    final_path = get_final_srt_path(project, get_settings().workspace_dir)
    write_text_atomic(final_path, work_path.read_text(encoding="utf-8"))
    _write_alignment_outputs(base_dir, alignment)
    return final_path


def _build_aligned_cues(
    project: Project, segments: list[Segment], settings
) -> tuple[list[dict], dict]:
    backend = None
    if settings.subtitle_alignment_enabled and settings.subtitle_whisper_model_path:
        from app.integrations.subtitle_alignment.faster_whisper import FasterWhisperAligner

        backend = FasterWhisperAligner(
            settings.subtitle_whisper_model_path,
            device=settings.subtitle_whisper_device,
            compute_type=settings.subtitle_whisper_compute_type,
            beam_size=settings.subtitle_whisper_beam_size,
        )

    project_config = load_project_config(project)
    configured_language = project_config.get("voice_language") or project_config.get("language")
    cue_values: list[dict] = []
    results = []
    current_ms = 0
    for segment in segments:
        if segment.duration is None:
            raise ValueError(f"Segment {segment.segment_id} has no audio duration")
        global_start = (
            round(float(segment.start_time) * 1000)
            if segment.start_time is not None
            else current_ms
        )
        duration_ms = round(float(segment.duration) * 1000)
        global_end = (
            round(float(segment.end_time) * 1000)
            if segment.end_time is not None
            else global_start + duration_ms
        )
        if abs((global_end - global_start) - duration_ms) > 80:
            raise ValueError(f"Segment {segment.segment_id} 时间轴与音频时长误差超过 80ms")
        language = alignment_service.infer_language(segment.text, configured_language)
        result = alignment_service.align_segment(
            segment_id=segment.segment_id,
            display_text=segment.text,
            language=language,
            duration_ms=duration_ms,
            audio_path=Path(segment.audio_path) if segment.audio_path else None,
            backend=backend,
            min_duration_ms=settings.subtitle_min_cue_duration_ms,
            max_duration_ms=settings.subtitle_max_cue_duration_ms,
            max_display_units=settings.subtitle_max_display_units,
        )
        serialized = result.model_dump(mode="json")
        serialized["global_start_ms"] = global_start
        serialized["global_end_ms"] = global_end
        results.append(serialized)
        for cue_index, cue in enumerate(result.cues, start=1):
            cue_values.append(
                {
                    "id": f"{project.id}:sub_{segment.segment_id}_{cue_index:02d}",
                    "source_segment_id": segment.id,
                    "cue_index": cue_index,
                    "start_ms": global_start + cue.local_start_ms,
                    "end_ms": global_start + cue.local_end_ms,
                    "text": cue.text,
                }
            )
        current_ms = global_end
    return cue_values, {
        "version": 1,
        "mode": "accurate" if backend is not None else "heuristic_fallback",
        "segments": results,
    }


def _write_alignment_outputs(base_dir: Path, alignment: dict) -> None:
    alignment_path = base_dir / "subtitles" / "alignment.json"
    write_json_atomic(alignment_path, alignment)
    segments = alignment["segments"]
    review = [item for item in segments if item["status"] != "passed"]
    report = {
        "passed": not review,
        "segment_count": len(segments),
        "review_count": len(review),
        "issues": [
            {
                "type": "subtitle_alignment_low_confidence",
                "severity": "warning",
                "segment_id": item["segment_id"],
                "confidence": item["confidence"],
                "backend": item["backend"],
                "message": item.get("error")
                or "该段未获得足够的本地 ASR 时间锚点，请人工复核字幕边界",
            }
            for item in review
        ],
    }
    write_json_atomic(base_dir / "reports" / "subtitle_qa.json", report)


def read_alignment_outputs(project: Project) -> dict:
    base_dir = get_project_work_dir(project, get_settings().workspace_dir)
    alignment_path = base_dir / "subtitles" / "alignment.json"
    report_path = base_dir / "reports" / "subtitle_qa.json"
    if not alignment_path.is_file():
        raise ValueError("项目尚未生成字幕对齐数据")
    return {
        "alignment": json.loads(alignment_path.read_text(encoding="utf-8")),
        "qa": (
            json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else None
        ),
        "alignment_path": str(alignment_path),
        "qa_path": str(report_path),
    }


def _write_srt(path: Path, cues: list[tuple[float, float, str]]) -> None:
    blocks = []
    for index, (start, end, text) in enumerate(cues, start=1):
        clean_text = _clean_srt_text(text)
        blocks.append(
            f"{index}\n{seconds_to_srt_time(start)} --> {seconds_to_srt_time(end)}\n{clean_text}"
        )
    write_text_atomic(path, "\n\n".join(blocks) + "\n")


def _clean_srt_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.replace("\\N", "\n").strip()
